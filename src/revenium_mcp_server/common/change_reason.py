"""The optional reason a caller gives for changing a guardrail, recorded on its change history."""

from dataclasses import dataclass
from typing import Any, Collection, Dict, Mapping, Optional, Tuple

from ..client import ReveniumAPIError
from ..change_reason_contract import (
    CHANGE_REASON_FIELD,
    CHANGE_REASON_MAX_LENGTH,
    normalized_change_reason,
)
from .error_handling import ErrorCodes, ToolError, create_structured_validation_error
from .validation import refuse_arguments_the_action_ignores

CHANGE_REASON_ARGUMENT = "change_reason"

CHANGE_REASON_FIELD_NOTE = (
    "Optional: why you are making this change, read back as reason on the change history. "
    f"Plain text, trimmed, up to {CHANGE_REASON_MAX_LENGTH} characters; an empty value means "
    "no reason. Write-only: never returned, so a read never carries one to send back. A reason "
    "sent with a save that changes nothing is dropped, unless the platform records that save "
    "anyway because a different person or API key made it."
)


def checked_change_reason(
    reason: Optional[str], *, field: str = CHANGE_REASON_ARGUMENT
) -> Optional[str]:
    """The reason as the platform keeps it, refused here when the platform would refuse its length.

    Counted in code points after trimming, as the platform's ChangeReason.normalize counts.
    The refusal never quotes the reason.
    """
    reason = normalized_change_reason(reason)
    if reason is not None and len(reason) > CHANGE_REASON_MAX_LENGTH:
        raise create_structured_validation_error(
            message=(
                f"{field} is {len(reason)} characters after trimming; the platform takes at most "
                f"{CHANGE_REASON_MAX_LENGTH}. Nothing was sent."
            ),
            field=field,
            suggestions=[f"Shorten {field} to at most {CHANGE_REASON_MAX_LENGTH} characters"],
        )
    return reason


def delete_refusal_is_id_or_change_reason(error: Exception, change_reason: Optional[str]) -> bool:
    """Whether a delete's refusal can mean the id or the reason.

    The platform checks access to the id before it reads the reason and answers an id it cannot
    use and a reason it refuses with the same 400; without a reason the 400 can only mean the id.
    """
    return (
        isinstance(error, ReveniumAPIError)
        and error.status_code == 400
        and change_reason is not None
    )


def id_or_change_reason_cause(resource: str) -> str:
    """Why a delete with a reason was answered with a 400, naming both causes the 400 can mean.

    The platform answers an id it cannot use and a reason it refuses with the same 400. The
    platform's words are left out, so the answer never tells whether a resource with this id
    exists elsewhere.
    """
    return (
        f"either no accessible {resource} has this id, or the platform refused the change reason "
        f"(it takes plain text up to {CHANGE_REASON_MAX_LENGTH} characters and refuses a few "
        "values it reserves)."
    )


def id_or_change_reason_refused(
    resource: str, id_field: str, resource_id: str, *, list_call: str
) -> ToolError:
    """The error for a delete with a reason that the platform answered with a 400."""
    return ToolError(
        message=(
            f"{resource.capitalize()} {resource_id!r} was not deleted: "
            f"{id_or_change_reason_cause(resource)}"
        ),
        error_code=ErrorCodes.INVALID_VALUE,
        field=id_field,
        suggestions=[
            f"Verify the {resource} ID exists using {list_call}",
            f"Send a different {CHANGE_REASON_ARGUMENT}, or delete without one",
        ],
    )


def change_reason_field_schema() -> Dict[str, Any]:
    """The JSON schema of the ``changeReason`` field a create or update body takes."""
    return {
        "type": ["string", "null"],
        "maxLength": CHANGE_REASON_MAX_LENGTH,
        "description": CHANGE_REASON_FIELD_NOTE,
    }


@dataclass(frozen=True)
class ChangeReasonArgument:
    """How one tool takes ``change_reason``: the actions that read it, and where its writes take one."""

    readers: Tuple[str, ...]
    data_argument: str

    def _where_a_write_takes_it(self) -> str:
        return f"the create or update action with {CHANGE_REASON_FIELD} inside {self.data_argument}"

    def description(self) -> str:
        """Describe the ``change_reason`` argument for the tool's schema and capabilities."""
        return (
            f"{' and '.join(self.readers)} only: why it is deleted, read back as reason on the "
            f"change history (plain text, up to {CHANGE_REASON_MAX_LENGTH} characters). To record "
            f"why you create or update it, use {self._where_a_write_takes_it()}. It is sent in "
            "the request URL, where access logs can record it, so keep secrets out of it"
        )

    def schema(self) -> Dict[str, Any]:
        """The JSON schema of the ``change_reason`` argument."""
        return {
            "type": "string",
            "maxLength": CHANGE_REASON_MAX_LENGTH,
            "description": self.description(),
        }

    def capability_text(self) -> str:
        """The ``change_reason`` entry of a reader action in the tool's capabilities."""
        return "str (optional) - " + self.description()

    def refuse_outside_readers(
        self,
        action: str,
        arguments: Mapping[str, Any],
        *,
        known_actions: Collection[str],
    ) -> None:
        """Refuse ``change_reason`` on any other action, naming where a write takes its reason."""
        refuse_arguments_the_action_ignores(
            action,
            arguments,
            (CHANGE_REASON_ARGUMENT,),
            honoured_by=self.readers,
            known_actions=known_actions,
            alternative=f"To record why you create or update it, use {self._where_a_write_takes_it()}",
        )


ALERT_CHANGE_REASON = ChangeReasonArgument(readers=("delete", "clear_all"), data_argument="anomaly_data")
COST_CONTROL_CHANGE_REASON = ChangeReasonArgument(readers=("delete",), data_argument="control_data")
