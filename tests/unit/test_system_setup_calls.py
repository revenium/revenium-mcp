"""BACK-4743: every setup sub-tool names its calls through one neutral renderer."""

from src.revenium_mcp_server.tools_decomposed import email_verification, system_setup
from src.revenium_mcp_server.tools_decomposed.system_setup_calls import setup_call


def test_a_call_without_arguments_names_only_the_action():
    assert setup_call("show_welcome") == "get_system_setup(action='show_welcome')"


def test_arguments_follow_the_action_in_the_order_given():
    assert (
        setup_call("validate_email", email="ops@company.com", confirm_completion=True)
        == "get_system_setup(action='validate_email', email='ops@company.com', confirm_completion=True)"
    )


def test_system_setup_and_the_email_tool_share_the_neutral_renderer():
    assert system_setup.setup_call is setup_call
    assert email_verification.setup_call is setup_call
