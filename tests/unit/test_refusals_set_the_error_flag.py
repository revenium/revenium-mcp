"""A refused call carries the MCP error flag, never a plain success.

BACK-5086: system setup's email check and setup completion, the usage-meter
create preview and the capability check answered their refusals as ordinary
content. An MCP client reads the error flag, not the prose, so it took each
refusal for a result and moved on.

The sweep at the bottom reads every module under ``tools_decomposed/`` and
fails when a handler hands a refusal back as content again.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Dict, Iterator, List, Set, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManagement,
    MeteringElementsValidator,
)
from tests.unit._registered_tool_harness import call_domain_tool

TOOLS_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "revenium_mcp_server"
    / "tools_decomposed"
)


class TestSystemSetupRefusals:
    async def test_validate_email_without_an_email_is_an_error(
        self, monkeypatch, tmp_path
    ):
        result, text = await call_domain_tool(
            monkeypatch, tmp_path, "get_system_setup", {"action": "validate_email"}
        )

        assert result.is_error is True, text
        assert "MISSING_PARAMETER" in text
        assert "email" in text

    @pytest.mark.parametrize("confirmation", [None, "maybe", False])
    async def test_complete_setup_without_confirmation_is_an_error(
        self, monkeypatch, tmp_path, confirmation
    ):
        arguments = {"action": "complete_setup"}
        if confirmation is not None:
            arguments["confirm_completion"] = confirmation

        result, text = await call_domain_tool(
            monkeypatch, tmp_path, "get_system_setup", arguments
        )

        assert result.is_error is True, text
        assert "Setup completion requires explicit confirmation" in text


class TestCapabilityVerificationRefusals:
    @pytest.mark.parametrize(
        "given",
        [
            {},
            {"resource_type": "products"},
            {"resource_type": "products", "value": "USD"},
        ],
    )
    async def test_verify_capability_with_a_missing_parameter_is_an_error(
        self, monkeypatch, tmp_path, given
    ):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "get_capabilities",
            {"action": "verify_capability", **given},
        )

        assert result.is_error is True, text
        assert "Missing required parameters for verify_capability" in text
        assert "capability_name" in text


def _rejecting_ucm_helper() -> MagicMock:
    helper = MagicMock()
    helper.ucm.get_capabilities = AsyncMock(
        return_value={
            "schema": {"element_data": {"required": ["name", "type"]}},
            "validation_rules": {"type": {"enum": ["NUMBER", "STRING"]}},
        }
    )
    return helper


class TestUsageMeterCreatePreview:
    async def test_preview_of_an_invalid_type_refuses_and_names_the_field(self):
        tool = MeteringElementsManagement()
        tool.validator = MeteringElementsValidator(_rejecting_ucm_helper())
        tool.get_client = AsyncMock(return_value=MagicMock())

        with pytest.raises(ToolError) as refused:
            await tool.handle_action(
                "create",
                {"dry_run": True, "element_data": {"name": "meter", "type": "BOOLEAN"}},
            )

        assert "Invalid type 'BOOLEAN'" in refused.value.message
        assert refused.value.field == "element_data"

    async def test_preview_refuses_with_the_live_create_message(self):
        tool = MeteringElementsManagement()
        tool.validator = MeteringElementsValidator(_rejecting_ucm_helper())
        tool.get_client = AsyncMock(return_value=MagicMock())
        invalid = {"element_data": {"name": "meter", "type": "BOOLEAN"}}

        with pytest.raises(ToolError) as previewed:
            await tool.handle_action("create", {**invalid, "dry_run": True})
        with pytest.raises(ToolError) as live:
            await tool.handle_action("create", dict(invalid))

        assert previewed.value.message == live.value.message

    async def test_preview_without_a_type_is_an_error(self, monkeypatch, tmp_path):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "manage_usage_meters",
            {"action": "create", "dry_run": True, "element_data": {"name": "meter"}},
        )

        assert result.is_error is True, text
        assert "type" in text

    async def test_a_valid_preview_is_not_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            ReveniumClient,
            "get_metering_element_definitions",
            AsyncMock(return_value={"page": {"totalPages": 0, "totalElements": 0}}),
        )
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "manage_usage_meters",
            {
                "action": "create",
                "dry_run": True,
                "element_data": {"name": "meter", "type": "NUMBER"},
            },
        )

        assert result.is_error is False, text
        assert "DRY RUN" in text

    async def test_a_validate_report_on_invalid_data_is_not_an_error(
        self, monkeypatch, tmp_path
    ):
        result, text = await call_domain_tool(
            monkeypatch,
            tmp_path,
            "manage_usage_meters",
            {"action": "validate", "element_data": {"name": "meter"}},
        )

        assert result.is_error is False, text
        assert "Missing required field: type" in text


# Answers whose headline names a failure but which are the verdict the caller
# asked for, not a refusal of the call. Keyed by module and headline text.
VERDICT_ANSWERS: Dict[Tuple[str, str], str] = {
    ("metering_management.py", "❌ **Validation Failed**"): (
        "validate reports whether a transaction is well formed; invalid data is its answer"
    ),
    ("metering_management.py", "**Transaction Not Found**"): (
        "get_transaction_status reports Found: No for an id this server never submitted"
    ),
}

# Handlers that catch an exception and still answer with content because the
# exception is the caller's answer, not a failure of the call.
CAUGHT_EXCEPTION_ANSWERS: Dict[Tuple[str, str], str] = {
    ("email_verification.py", "_handle_validate_email"): (
        "validate_email reports a malformed address as its verdict"
    ),
    ("business_analytics_management.py", "_handle_get_skill"): (
        "a 404 on a known skill is the empty state of a window with no usage"
    ),
}

REFUSAL_HEADLINE = re.compile(r"error|failed|invalid|missing|not found|refused", re.I)


def _modules() -> Iterator[Tuple[str, ast.Module]]:
    for path in sorted(TOOLS_DIR.glob("*.py")):
        yield path.name, ast.parse(path.read_text(encoding="utf-8"))


def _called_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _calls(node: ast.AST) -> List[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _functions(tree: ast.AST) -> List[ast.AST]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _returns(function: ast.AST) -> List[ast.Return]:
    return [n for n in ast.walk(function) if isinstance(n, ast.Return) and n.value]


def _formatted_error_builders() -> Set[str]:
    """Functions whose answer is a formatted structured error string."""
    builders: Set[str] = set()
    for _, tree in _modules():
        for function in _functions(tree):
            for returned in _returns(function):
                value = returned.value
                if (
                    isinstance(value, ast.Call)
                    and _called_name(value) == "format_structured_error"
                ):
                    builders.add(function.name)
    return builders


def _text_headline(text_value: ast.expr) -> str:
    """The first line of literal text, in source order rather than walk order."""
    literals = [
        node
        for node in ast.walk(text_value)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip()
    ]
    if not literals:
        return ""
    first = min(literals, key=lambda node: (node.lineno, node.col_offset))
    return first.value.strip().splitlines()[0]


def _content_headlines(returned: ast.Return) -> Iterator[str]:
    for call in _calls(returned):
        if _called_name(call) != "TextContent":
            continue
        for keyword in call.keywords:
            if keyword.arg == "text":
                yield _text_headline(keyword.value)


def _content_answers_to_caught_exceptions() -> Set[Tuple[str, str]]:
    """(module, function) pairs where an except clause returns TextContent."""
    found: Set[Tuple[str, str]] = set()
    for module, tree in _modules():
        for function in _functions(tree):
            for handler in ast.walk(function):
                if not isinstance(handler, ast.ExceptHandler):
                    continue
                if any(
                    _called_name(call) == "TextContent"
                    for returned in _returns(handler)
                    for call in _calls(returned)
                ):
                    found.add((module, function.name))
    return found


def _headline_of(source: str) -> str:
    call = ast.parse(source, mode="eval").body
    assert isinstance(call, ast.Call)
    return next(_content_headlines(ast.Return(value=call)))


class TestHeadlineReading:
    def test_a_concatenated_text_is_read_from_its_first_literal(self):
        source = 'TextContent(type="text", text="**Error**: " + detail + "try again")'

        assert _headline_of(source) == "**Error**:"

    def test_an_f_string_is_read_from_its_first_literal(self):
        source = 'TextContent(type="text", text=f"**Failed**: {reason}\\n\\nretry")'

        assert _headline_of(source) == "**Failed**:"


class TestNoHandlerAnswersARefusalAsContent:
    def test_no_function_puts_a_structured_error_into_content(self):
        offenders = [
            f"{module}::{function.name}"
            for module, tree in _modules()
            for function in _functions(tree)
            if {"format_structured_error", "TextContent"}
            <= {_called_name(call) for call in _calls(function)}
        ]

        assert offenders == [], (
            "These functions return a structured error as content, so the answer "
            "carries no error flag. Raise it with raise_structured_error instead: "
            f"{offenders}"
        )

    def test_no_handler_returns_a_formatted_error_string(self):
        builders = _formatted_error_builders()
        offenders = [
            f"{module}::{function.name} returns {_called_name(returned.value)}()"
            for module, tree in _modules()
            for function in _functions(tree)
            if function.name not in builders
            for returned in _returns(function)
            if isinstance(returned.value, ast.Call)
            and _called_name(returned.value) in builders
        ]

        assert offenders == [], (
            "These handlers return a formatted refusal as their answer. Pass it "
            f"to raise_refusal so the error flag is set: {offenders}"
        )

    def test_no_handler_answers_with_a_refusal_headline(self):
        offenders = [
            f"{module}:{returned.lineno} {headline!r}"
            for module, tree in _modules()
            for returned in (r for f in _functions(tree) for r in _returns(f))
            for headline in _content_headlines(returned)
            if REFUSAL_HEADLINE.search(headline)
            and (module, headline) not in VERDICT_ANSWERS
        ]

        assert offenders == [], (
            "These answers open with a failure but are returned as content, so "
            "the error flag is not set. Raise with raise_refusal, or add the "
            f"answer to VERDICT_ANSWERS with the reason it is a verdict: {offenders}"
        )

    def test_every_verdict_exemption_still_exists(self):
        present = {
            (module, headline)
            for module, tree in _modules()
            for returned in (r for f in _functions(tree) for r in _returns(f))
            for headline in _content_headlines(returned)
        }

        assert set(VERDICT_ANSWERS) <= present

    def test_no_caught_exception_is_answered_as_content(self):
        offenders = sorted(
            f"{module}::{function}"
            for module, function in _content_answers_to_caught_exceptions()
            if (module, function) not in CAUGHT_EXCEPTION_ANSWERS
        )

        assert offenders == [], (
            "These handlers catch an exception and answer with content, so a "
            "failure reads as a success. Raise with raise_refusal, or add the "
            "handler to CAUGHT_EXCEPTION_ANSWERS with the reason the exception "
            f"is the caller's answer: {offenders}"
        )

    def test_every_caught_exception_exemption_still_exists(self):
        assert set(CAUGHT_EXCEPTION_ANSWERS) <= _content_answers_to_caught_exceptions()
