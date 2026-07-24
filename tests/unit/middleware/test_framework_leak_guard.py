"""Tests for FrameworkLeakGuardMiddleware (BACK-1312).

Verifies that Pydantic ValidationError raised at the FastMCP signature-binding
layer never reaches the caller as a raw envelope (no `errors.pydantic.dev` URL,
no `call[<tool>]` framing, no internal type tags). Translation must produce a
caller-actionable message that names the tool, the field, the value, and offers
a `did you mean` suggestion when the field is unrecognized.
"""
from __future__ import annotations

from typing import Optional, Union

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


def _validation_error(callable_, kwargs):
    """Trigger a Pydantic ValidationError with the same shape FastMCP produces.

    FastMCP routes incoming tool-call args through `TypeAdapter(callable).validate_python(kwargs)`.
    Hitting the same code path here gives us realistic error fixtures for the
    middleware translator.
    """
    ta = TypeAdapter(callable_)
    try:
        ta.validate_python(kwargs)
    except ValidationError as exc:
        return exc
    raise AssertionError("expected ValidationError, validation passed")


# Sample tool signature used as a stand-in for a real registered tool.
def _sample_tool(
    action: str = "list",
    product_id: str | None = None,
    page: int = 0,
    size: int = 20,
):
    return None


_ACCEPTED_PARAMS = ["action", "product_id", "page", "size"]


class TestTranslatePydanticError:
    """Unit tests for the pure translator function."""

    def test_unexpected_keyword_with_close_match_suggests_canonical_name(self):
        """`id` against [product_id, page, size] should suggest `product_id`."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        exc = _validation_error(_sample_tool, {"id": "X"})
        msg = translate_pydantic_error(exc, tool_name="manage_products", accepted_params=_ACCEPTED_PARAMS)

        assert "manage_products" in msg
        assert "'id'" in msg
        assert "product_id" in msg, f"expected 'did you mean: product_id' in: {msg!r}"
        assert_no_framework_leak(msg)

    def test_unexpected_keyword_no_close_match_omits_suggestion(self):
        """A wholly unrelated field name should not yield a misleading suggestion."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        exc = _validation_error(_sample_tool, {"xyzzy": "X"})
        msg = translate_pydantic_error(exc, tool_name="manage_products", accepted_params=_ACCEPTED_PARAMS)

        assert "'xyzzy'" in msg
        assert "Did you mean" not in msg, f"unexpected suggestion in: {msg!r}"
        assert_no_framework_leak(msg)

    def test_int_from_float_names_value_and_type(self):
        """`page=3.7` should explain the integer requirement and offer alternatives."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        exc = _validation_error(_sample_tool, {"page": 3.7})
        msg = translate_pydantic_error(exc, tool_name="manage_products", accepted_params=_ACCEPTED_PARAMS)

        assert "'page'" in msg
        assert "integer" in msg.lower()
        assert "3.7" in msg
        assert_no_framework_leak(msg)

    def test_string_type_for_int_input(self):
        """`name=12345` against `name: str` should report str-required + value."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        def callable_str_only(name: str = "x"):
            return None

        exc = _validation_error(callable_str_only, {"name": 12345})
        msg = translate_pydantic_error(exc, tool_name="slack_management", accepted_params=["name"])

        assert "'name'" in msg
        assert "string" in msg.lower()
        assert "12345" in msg
        assert_no_framework_leak(msg)

    def test_int_type_or_int_parsing_for_unparsable_string(self):
        """`page="abc"` should report integer requirement."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        exc = _validation_error(_sample_tool, {"page": "abc"})
        msg = translate_pydantic_error(exc, tool_name="manage_products", accepted_params=_ACCEPTED_PARAMS)

        assert "'page'" in msg
        assert "integer" in msg.lower()
        assert_no_framework_leak(msg)

    def test_multiple_errors_emitted_separately(self):
        """Two simultaneous errors should produce two paragraphs in one message."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        exc = _validation_error(_sample_tool, {"id": "X", "page": 3.7})
        msg = translate_pydantic_error(exc, tool_name="manage_products", accepted_params=_ACCEPTED_PARAMS)

        assert "'id'" in msg
        assert "'page'" in msg
        assert "\n\n" in msg, f"expected blank-line-separated paragraphs in: {msg!r}"
        assert_no_framework_leak(msg)

    def test_unknown_error_type_sanitized(self):
        """Error types we don't have a custom message for should still be sanitized."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        # Synthesize a ValidationError with an error type we don't special-case.
        # `none_required` is rare but real.
        def callable_with_none(value: None = None):
            return None

        exc = _validation_error(callable_with_none, {"value": 1})
        msg = translate_pydantic_error(exc, tool_name="some_tool", accepted_params=["value"])

        assert "'value'" in msg
        assert_no_framework_leak(msg)

    def test_no_accepted_params_omits_suggestion_gracefully(self):
        """Empty accepted_params should not crash; suggestion is just omitted."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )

        exc = _validation_error(_sample_tool, {"id": "X"})
        msg = translate_pydantic_error(exc, tool_name="manage_products", accepted_params=[])

        assert "manage_products" in msg
        assert "'id'" in msg
        assert "Did you mean" not in msg
        assert_no_framework_leak(msg)

    def test_string_type_example_uses_placeholder_not_raw_value(self):
        """The string_type example must not embed the raw input verbatim.
        Otherwise None/dict/list values produce misleading examples like
        `Pass a string (e.g. field="None")` (Greptile review)."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )
        # Trigger string_type by passing None/non-string to a str-typed field.
        def callable_str(name: str = "x"):
            return None
        exc = _validation_error(callable_str, {"name": None})
        msg = translate_pydantic_error(exc, tool_name="t", accepted_params=["name"])
        # Hardcoded placeholder, not the raw None
        assert 'name="some_value"' in msg or 'name = "some_value"' in msg.replace(' ', '')
        # Original value is still surfaced for diagnostics
        assert "None" in msg

    def test_suggest_param_returns_all_tier1_matches_when_multiple(self):
        """When multiple `*_id` candidates exist, suggest all of them rather
        than dict-order luck (Greptile review)."""
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )
        def callable_multi_id(
            action: str = "x",
            product_id: str | None = None,
            customer_id: str | None = None,
            subscription_id: str | None = None,
        ):
            return None
        exc = _validation_error(callable_multi_id, {"id": "X"})
        msg = translate_pydantic_error(
            exc,
            tool_name="t",
            accepted_params=["action", "product_id", "customer_id", "subscription_id"],
        )
        # All three *_id candidates must appear in the suggestion.
        assert "product_id" in msg
        assert "customer_id" in msg
        assert "subscription_id" in msg


class TestFrameworkLeakGuardMiddlewareIntegration:
    """End-to-end: build a real FastMCP server, register the middleware, call
    the tool with bad args, and verify the response is clean and isError."""

    @pytest.mark.asyncio
    async def test_middleware_intercepts_unexpected_keyword(self):
        from fastmcp import FastMCP, Client
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        srv = FastMCP("integration-test")

        @srv.tool()
        async def manage_widgets(action: str = "list", widget_id: str | None = None) -> str:
            return f"{action}:{widget_id}"

        srv.add_middleware(FrameworkLeakGuardMiddleware())

        async with Client(srv) as client:
            result = await client.call_tool(
                "manage_widgets", {"id": "abc"}, raise_on_error=False
            )

        assert result.is_error is True
        text = result.content[0].text
        assert "manage_widgets" in text
        assert "'id'" in text
        assert "widget_id" in text  # did-you-mean suggestion
        assert_no_framework_leak(text)

    @pytest.mark.asyncio
    async def test_middleware_intercepts_int_from_float(self):
        from fastmcp import FastMCP, Client
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        srv = FastMCP("integration-test")

        @srv.tool()
        async def list_things(page: int = 0, size: int = 20) -> str:
            return f"{page}:{size}"

        srv.add_middleware(FrameworkLeakGuardMiddleware())

        async with Client(srv) as client:
            result = await client.call_tool(
                "list_things", {"page": 3.7}, raise_on_error=False
            )

        assert result.is_error is True
        text = result.content[0].text
        assert "'page'" in text
        assert "integer" in text.lower()
        assert "3.7" in text
        assert_no_framework_leak(text)

    @pytest.mark.asyncio
    async def test_middleware_does_not_swallow_non_validation_exceptions(self):
        """Tool handler raising a non-validation exception must still bubble up."""
        from fastmcp import FastMCP, Client
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        srv = FastMCP("integration-test")

        @srv.tool()
        async def boom() -> str:
            raise RuntimeError("boom from handler")

        srv.add_middleware(FrameworkLeakGuardMiddleware())

        async with Client(srv) as client:
            result = await client.call_tool("boom", {}, raise_on_error=False)

        # FastMCP wraps the RuntimeError into an error response. The middleware
        # must not have intercepted it (we'd see our "Field 'X'" framing if so).
        assert result.is_error is True
        text = result.content[0].text
        assert "Field '" not in text, (
            "non-ValidationError unexpectedly translated by middleware"
        )

    @pytest.mark.asyncio
    async def test_middleware_does_not_catch_internal_basemodel_validation(self):
        """ValidationError raised inside the tool body — e.g. from a BaseModel
        constructed with bad data — must propagate untranslated. The middleware
        only translates errors from the FastMCP signature-binding layer
        (TypeAdapter title `call[<tool>]`)."""
        from fastmcp import FastMCP, Client
        from pydantic import BaseModel
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        class _InternalModel(BaseModel):
            internal_field: int

        srv = FastMCP("integration-test")

        @srv.tool()
        async def construct_internal(passthrough: str = "x") -> str:
            # Raises ValidationError with title='_InternalModel', NOT 'call[...]'.
            _InternalModel(internal_field="not_an_int")
            return passthrough

        srv.add_middleware(FrameworkLeakGuardMiddleware())

        async with Client(srv) as client:
            result = await client.call_tool(
                "construct_internal", {"passthrough": "ok"}, raise_on_error=False
            )

        # The handler raised a ValidationError; middleware MUST NOT have rewritten
        # it as `Field 'internal_field' is not a recognized parameter of construct_internal`.
        assert result.is_error is True
        text = result.content[0].text
        assert "is not a recognized parameter" not in text, (
            "middleware mis-translated a tool-body ValidationError as a "
            "caller-side parameter-mismatch error"
        )

    @staticmethod
    def _make_ctx(tool_name: str = "manage_products"):
        """Minimal MiddlewareContext stand-in for direct on_call_tool tests."""

        class _Msg:
            name = tool_name

        class _Ctx:
            message = _Msg()
            fastmcp_context = None

        return _Ctx()

    @pytest.mark.asyncio
    async def test_middleware_translates_fastmcp_wrapped_validation_error(self):
        """fastmcp >= 3.4 (#4128) wraps the binding-layer pydantic error in
        fastmcp's own ValidationError with the pydantic original as __cause__.
        The guard must translate via the cause. Simulated directly so this
        contract is exercised on every fastmcp version in the matrix."""
        from fastmcp.exceptions import ToolError
        from fastmcp.exceptions import ValidationError as FastMCPValidationError
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        pydantic_exc = _validation_error(_sample_tool, {"id": "abc"})

        async def call_next(_context):
            try:
                raise pydantic_exc
            except ValidationError:
                raise FastMCPValidationError(str(pydantic_exc)) from pydantic_exc

        mw = FrameworkLeakGuardMiddleware()
        with pytest.raises(ToolError) as exc_info:
            await mw.on_call_tool(self._make_ctx(), call_next)

        text = str(exc_info.value)
        assert "manage_products" in text
        assert "'id'" in text
        assert_no_framework_leak(text)

    @pytest.mark.asyncio
    async def test_middleware_reraises_wrapped_error_without_pydantic_cause(self):
        """A fastmcp ValidationError with no pydantic cause (not a binding
        failure) must propagate untouched."""
        from fastmcp.exceptions import ValidationError as FastMCPValidationError
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        async def call_next(_context):
            raise FastMCPValidationError("tool-internal validation failure")

        mw = FrameworkLeakGuardMiddleware()
        with pytest.raises(FastMCPValidationError):
            await mw.on_call_tool(self._make_ctx(), call_next)

    @pytest.mark.asyncio
    async def test_middleware_reraises_wrapped_non_binding_pydantic_error(self):
        """A fastmcp ValidationError whose pydantic cause is NOT a binding
        error (title != call[<tool>], e.g. a tool-body BaseModel failure that
        fastmcp wrapped) must propagate untouched — the wrapped-path analogue
        of the BACK-1312 title-gate rule."""
        from pydantic import BaseModel
        from fastmcp.exceptions import ValidationError as FastMCPValidationError
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            FrameworkLeakGuardMiddleware,
        )

        class _InternalModel(BaseModel):
            internal_field: int

        try:
            _InternalModel(internal_field="not_an_int")
            raise AssertionError("expected ValidationError")
        except ValidationError as exc:
            internal_exc = exc

        async def call_next(_context):
            try:
                raise internal_exc
            except ValidationError:
                raise FastMCPValidationError(str(internal_exc)) from internal_exc

        mw = FrameworkLeakGuardMiddleware()
        with pytest.raises(FastMCPValidationError) as exc_info:
            await mw.on_call_tool(self._make_ctx(), call_next)

        # Not rewritten as a caller-side parameter-mismatch error.
        assert "is not a recognized parameter" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_real_server_has_middleware_registered(self):
        """create_enhanced_server must register the middleware. End-to-end smoke."""
        from fastmcp import Client
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        srv = create_enhanced_server()

        # Confirm registration without depending on FastMCP internal API:
        # add a probe tool, call with bad arg, verify clean output.
        @srv.tool()
        async def _probe_widget(widget_id: str | None = None) -> str:
            return widget_id or "x"

        async with Client(srv) as client:
            result = await client.call_tool(
                "_probe_widget", {"id": "abc"}, raise_on_error=False
            )

        assert result.is_error is True
        text = result.content[0].text
        assert_no_framework_leak(text)
        assert "_probe_widget" in text
        assert "widget_id" in text


class TestUnionFieldMessages:
    """A Union[int, str] field produces one pydantic error per branch — the
    translated output must be ONE coherent message, not stacked contradictory
    'must be an integer' + 'must be a string' paragraphs."""

    def test_union_int_str_field_yields_single_message(self):
        from src.revenium_mcp_server.middleware.framework_leak_guard import (
            translate_pydantic_error,
        )
        def _union_tool(input_tokens: Optional[Union[int, str]] = None):
            return None

        exc = _validation_error(_union_tool, {"input_tokens": 3.7})
        msg = translate_pydantic_error(
            exc, tool_name="manage_metering", accepted_params=["input_tokens"]
        )
        assert msg.count("'input_tokens'") == 1, f"stacked messages: {msg!r}"
        assert "integer" in msg
        assert "3.7" in msg
        assert_no_framework_leak(msg)
