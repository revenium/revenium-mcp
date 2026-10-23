"""Calls help must never print bare, because the server only answers them through system_setup (BACK-4743).

Each entry is the open-paren form, so `update_email(email='your@email.com')`
matches while `system_setup(action='update_email', ...)` does not.
"""

BARE_SETUP_CALLS = (
    "show_welcome()",
    "setup_checklist()",
    "environment_status()",
    "check_requirements()",
    "setup_guidance()",
    "complete_setup()",
    "`get_examples()`",
    "check_status()",
    "test_configuration()",
    "update_email(",
    "validate_email(",
    "verify_email_setup(",
)


def bare_setup_calls_in(text: str) -> list:
    return [call for call in BARE_SETUP_CALLS if call in text]
