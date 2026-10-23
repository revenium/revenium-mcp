"""How help text names a call through system_setup, the tool every server registers for setup actions."""


def setup_call(action: str, **arguments: object) -> str:
    rendered = "".join(f", {name}={value!r}" for name, value in arguments.items())
    return f"system_setup(action='{action}'{rendered})"
