"""Turning the caller's ``email``, ``notificationAddresses`` and Slack channels into one list each."""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..common.error_handling import create_structured_validation_error


RECIPIENT_FIELDS = ("email", "notificationAddresses", "notification_addresses")
NOTIFICATION_TARGET_FIELDS = ("notificationAddresses", "slackConfigurations", "webhookConfigurations")
NO_RECIPIENT_MESSAGE = "Email address is required for alert notifications"


def _as_address_list(addresses: Any, field: str = "notificationAddresses") -> List[str]:
    if addresses is None:
        return []
    if isinstance(addresses, str):
        return [addresses]
    if isinstance(addresses, list) and all(isinstance(address, str) for address in addresses):
        return addresses
    raise create_structured_validation_error(
        message=f"{field} must be an email address or a list of email addresses",
        field=field,
        value=addresses,
        suggestions=[f'Send {field} as "a@example.com" or ["a@example.com", "b@example.com"]'],
    )


def _as_slack_id_list(ids: Any, field: str) -> List[str]:
    if ids is None:
        return []
    if isinstance(ids, str):
        return [ids]
    if isinstance(ids, list) and all(isinstance(config_id, str) for config_id in ids):
        return ids
    raise create_structured_validation_error(
        message=f"{field} must be a Slack configuration id or a list of them",
        field=field,
        value=ids,
        suggestions=[f'Send {field} as "slack_1" or ["slack_1", "slack_2"]'],
    )


def union_named_recipients(named: Iterable[Tuple[str, Any]]) -> List[str]:
    """Every address under each ``(field, value)`` pair, once each, in the order given.

    Each value is validated under its own field name; addresses are compared without
    regard to case, and the first spelling is kept.
    """
    candidates: List[str] = []
    for field, addresses in named:
        candidates.extend(_as_address_list(addresses, field))
    return _distinct_addresses(candidates)


def union_slack_configurations(named: Iterable[Tuple[str, Any]]) -> List[str]:
    """Every Slack configuration id under each ``(field, value)`` pair, once each, in order."""
    candidates: List[str] = []
    for field, ids in named:
        candidates.extend(_as_slack_id_list(ids, field))
    return list(dict.fromkeys(config_id.strip() for config_id in candidates if config_id.strip()))


def union_recipients(email: Any, notification_addresses: Any) -> List[str]:
    """Every address from ``email`` and ``notificationAddresses``, once each, in the order given.

    Addresses are compared without regard to case, and the first spelling is kept.
    """
    return union_named_recipients(
        [("email", email), ("notificationAddresses", notification_addresses)]
    )


def update_recipients(update_data: Dict[str, Any]) -> Optional[List[str]]:
    """The recipient list an update names under any recipient field, once each.

    None when the update names no recipient field. Each field is validated under its
    own name, and an update whose every named address is blank is refused.
    """
    named = [field for field in RECIPIENT_FIELDS if field in update_data]
    if not named:
        return None
    candidates: List[str] = []
    for field in named:
        candidates.extend(_as_address_list(update_data[field], field))
    recipients = _distinct_addresses(candidates)
    if candidates and not recipients:
        raise create_structured_validation_error(
            message="The update names a recipient but every address is blank; nothing was updated",
            field=named[0],
            value=candidates,
            suggestions=["Send email='user@example.com' or notificationAddresses=[...]"],
        )
    return recipients


def _distinct_addresses(candidates: List[str]) -> List[str]:
    recipients: List[str] = []
    seen = set()
    for candidate in candidates:
        address = candidate.strip()
        if address and address.lower() not in seen:
            seen.add(address.lower())
            recipients.append(address)
    return recipients


def refuse_an_update_that_notifies_nobody(
    changes: Mapping[str, Any], merged: Mapping[str, Any]
) -> None:
    """Refuse an update that empties the alert's last email, Slack channel and webhook, as create refuses one."""
    if not any(field in changes for field in NOTIFICATION_TARGET_FIELDS):
        return
    if any(merged.get(field) for field in NOTIFICATION_TARGET_FIELDS):
        return
    raise create_structured_validation_error(
        message=f"{NO_RECIPIENT_MESSAGE}; nothing was updated",
        field="notificationAddresses",
        value=[],
        suggestions=[
            "Keep at least one email in notificationAddresses, one Slack channel in "
            "slackConfigurations or one webhook in webhookConfigurations",
            "Leave notificationAddresses, slackConfigurations and webhookConfigurations out to keep the stored ones",
        ],
    )
