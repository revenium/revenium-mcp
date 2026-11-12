"""The platform's change reason on a guardrail write, as ChangeReason.normalize defines it.

Shared by the client, which sends it on deletes, and the tool layer, which checks it.
"""

from typing import Optional

CHANGE_REASON_FIELD = "changeReason"
CHANGE_REASON_MAX_LENGTH = 500


def normalized_change_reason(reason: Optional[str]) -> Optional[str]:
    """The reason as the platform keeps it: trimmed, and None when nothing is left."""
    return (reason or "").strip() or None
