"""Product plan values read off the generated platform contract.

The generated module is large and nothing on the startup path needs it, so it
is imported on first use, as ``_tool_type_values`` in
``tools_decomposed/tool_management.py`` does.
"""

from enum import Enum
from functools import lru_cache
from typing import Tuple, get_args


@lru_cache(maxsize=1)
def platform_plan_currencies() -> Tuple[str, ...]:
    """Plan currencies in the order the platform lists them when it refuses one."""
    from .generated.hypercurrent_models import Plan  # noqa: PLC0415

    annotation = Plan.model_fields["currency"].annotation
    for candidate in (annotation, *get_args(annotation)):
        if isinstance(candidate, type) and issubclass(candidate, Enum):
            return tuple(str(member.value) for member in candidate)
    raise RuntimeError(
        "Plan.currency is no longer an enum in the generated models; refresh "
        "specs/openapi/hypercurrent.json and the generated models."
    )
