"""The Claude organizations whose Cowork activity routes to a team.

A team sees every Claude organization uuid it knows from its own Claude
Enterprise credentials and from links, each with a state. Linking routes that
organization's Cowork activity, and its spend, to the team; unlinking stops it.
Both writes preview with dry_run and run on manage_customers, which the client
confirms before calling because it is marked destructive.
"""

import re
from typing import Any, Dict, List, NoReturn, Optional

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)
from ..common.one_line import one_line

LIST_ACTION = "list_cowork_org_links"
LINK_ACTION = "link_cowork_org"
UNLINK_ACTION = "unlink_cowork_org"

COWORK_ORG_LINK_STATES = {
    "LINKED": "Linked to this team",
    "NOT_LINKED": "Not linked",
    "LINKED_BY_ANOTHER_ACCOUNT": "Linked by another account",
}

CLAUDE_ORG_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

COWORK_ORG_LINK_STATES_NOTE = (
    "LINKED means the organization's Cowork activity routes to this team. NOT_LINKED "
    "is an organization the team knows from one of its credentials that routes "
    "nowhere yet. LINKED_BY_ANOTHER_ACCOUNT routes to another account and cannot be "
    "linked from this one."
)

COWORK_ORG_LINK_EFFECT_NOTE = (
    "Linking routes the organization's Cowork activity, and the spend it records, to "
    "the team from then on. Linking an organization the team has already linked "
    "returns the existing link."
)

COWORK_ORG_UNLINK_EFFECT_NOTE = (
    "Unlinking stops the organization's Cowork activity routing to the team: new "
    "activity from it no longer reaches this team's costs and reports until someone "
    "links it again."
)

COWORK_ORG_LINK_MODES_NOTE = (
    "Pass exactly one of credential_id (one of the team's own Claude Enterprise "
    "credentials; the platform asks that key for its organization uuid) or "
    "claude_org_uuid (an organization uuid in 8-4-4-4-12 form, for an organization "
    "with no connected key)."
)

COWORK_ORG_UNLINK_PREVIEW_NOTE = (
    "unlink_cowork_org runs when called. Preview it first with dry_run=true, which "
    "reads the team's links to name the organization the link routes and sends no "
    "write, and run it only "
    "after the customer agrees to stop the routing."
)

COWORK_ORG_FEATURE_GATE_NOTE = (
    "The platform serves these actions only where Claude organization linking is "
    "enabled; elsewhere every call answers 403 Feature not available, which no role "
    "or key change fixes."
)

COWORK_ORG_TEAM_SCOPE_NOTE = (
    "team_id is optional; omitted, the team from the caller's auth configuration "
    "is used."
)


def resolve_cowork_team_id(
    arguments: Dict[str, Any], action: str, ambient_team_id: Optional[str]
) -> str:
    """The team named in team_id, else the caller's own team; a blank team_id is refused.

    A blank value silently falling back to the ambient team would run a write
    against a team the caller never named.
    """
    team_id = arguments.get("team_id")
    if team_id is None:
        if isinstance(ambient_team_id, str) and ambient_team_id.strip():
            return ambient_team_id.strip()
        raise create_structured_missing_parameter_error(
            parameter_name="team_id",
            action=action,
            examples={
                "usage": f"{action}(team_id='jR2kmLs')",
                "why": "No team_id was passed and the auth configuration names no team",
                "discover_teams": "list(resource_type='teams')",
            },
        )
    if isinstance(team_id, str) and team_id.strip():
        return team_id.strip()
    raise create_structured_validation_error(
        message=f"Invalid team_id: {team_id!r}",
        field="team_id",
        value=team_id,
        suggestions=[
            "team_id must be a non-empty Revenium team hashid string",
            "Omit team_id entirely to use the team from the auth configuration",
        ],
        examples={"usage": f"{action}(team_id='jR2kmLs')"},
    )


# The platform already holds a Cowork name to 40 code points with no quote,
# control or format character (CoworkOrgLinkStore); this bound only stops a value
# that bypassed that rule from flooding the listing.
_TOOL_NAME_MAX_LENGTH = 100


def _non_empty_string(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _display_name(value: Any) -> Optional[str]:
    """A team-set name flattened to one bounded line, or None when nothing readable is left."""
    if not isinstance(value, str):
        return None
    return one_line(value, _TOOL_NAME_MAX_LENGTH) or None


def _quoted(text: str) -> str:
    return '"' + text.replace('"', "'") + '"'


def build_link_request(arguments: Dict[str, Any]) -> Dict[str, str]:
    """The link body: exactly one of credentialId or claudeOrgUuid."""
    credential_id = arguments.get("credential_id")
    claude_org_uuid = arguments.get("claude_org_uuid")
    for field, value in (("credential_id", credential_id), ("claude_org_uuid", claude_org_uuid)):
        if value is not None and _non_empty_string(value) is None:
            raise create_structured_validation_error(
                message=f"Invalid {field}: {value!r}",
                field=field,
                value=value,
                suggestions=[f"{field} must be a non-empty string, or left out", COWORK_ORG_LINK_MODES_NOTE],
            )
    if credential_id is not None and claude_org_uuid is not None:
        raise create_structured_validation_error(
            message="Pass either credential_id or claude_org_uuid, not both",
            field="credential_id",
            value=credential_id,
            suggestions=[COWORK_ORG_LINK_MODES_NOTE],
            examples={
                "by_credential": f"{LINK_ACTION}(credential_id='cred_123')",
                "by_uuid": (
                    f"{LINK_ACTION}(claude_org_uuid='0f8e1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b')"
                ),
            },
        )
    if credential_id is not None:
        return {"credentialId": credential_id.strip()}
    if claude_org_uuid is not None:
        stripped = claude_org_uuid.strip()
        if not CLAUDE_ORG_UUID_PATTERN.match(stripped):
            raise create_structured_validation_error(
                message=f"Invalid claude_org_uuid: {claude_org_uuid!r}",
                field="claude_org_uuid",
                value=claude_org_uuid,
                suggestions=[
                    "claude_org_uuid is a Claude organization uuid in 8-4-4-4-12 form",
                    f"{LIST_ACTION}() shows the organization uuids the team already knows",
                ],
            )
        return {"claudeOrgUuid": stripped.lower()}
    raise create_structured_missing_parameter_error(
        parameter_name="claude_org_uuid",
        action=LINK_ACTION,
        examples={
            "by_uuid": f"{LINK_ACTION}(claude_org_uuid='0f8e1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b')",
            "by_credential": f"{LINK_ACTION}(credential_id='cred_123')",
            "modes": COWORK_ORG_LINK_MODES_NOTE,
        },
    )


def require_link_id(arguments: Dict[str, Any]) -> str:
    link_id = _non_empty_string(arguments.get("link_id"))
    if link_id is None:
        raise create_structured_missing_parameter_error(
            parameter_name="link_id",
            action=UNLINK_ACTION,
            examples={
                "usage": f"{UNLINK_ACTION}(link_id='aB3dE5f', dry_run=true)",
                "discover_links": f"{LIST_ACTION}() - the id of each LINKED organization",
            },
        )
    return link_id


def normalize_cowork_org_link(entry: Any) -> Optional[Dict[str, Any]]:
    """Project one upstream link onto its five fields, or None for an unusable entry."""
    if not isinstance(entry, dict):
        return None
    claude_org_uuid = _non_empty_string(entry.get("claudeOrgUuid"))
    if claude_org_uuid is None:
        return None
    state = entry.get("state")
    return {
        "claudeOrgUuid": claude_org_uuid,
        "state": state if isinstance(state, str) else "unknown",
        "linkId": _non_empty_string(entry.get("id")),
        "source": _non_empty_string(entry.get("source")),
        "toolName": _display_name(entry.get("toolName")),
    }


def _describe_state(state: str) -> str:
    return COWORK_ORG_LINK_STATES.get(state, f"Unrecognised state {state}")


def _format_link_line(link: Dict[str, Any]) -> str:
    details = [_describe_state(link["state"])]
    if link.get("linkId"):
        details.append(f"link id `{link['linkId']}`")
    if link.get("source"):
        details.append(f"source {link['source']}")
    tool_name = link.get("toolName")
    if tool_name:
        details.append(f"shown in Cowork as {_quoted(tool_name)}")
    return f"- `{link['claudeOrgUuid']}` - " + ", ".join(details)


def format_cowork_org_links_text(result: Dict[str, Any]) -> str:
    links: List[Dict[str, Any]] = result["links"]
    lines = [f"## Claude organizations for team {result['team_id']}", ""]
    if result.get("warning"):
        lines += [f"WARNING: {result['warning']}", ""]
    if not links and not result.get("warning"):
        lines += [
            "No Claude organizations are known for this team: it has no Claude "
            "Enterprise credential that names one and no link.",
            "",
        ]
    elif links:
        known_counts = {
            label: sum(1 for link in links if link["state"] == state)
            for state, label in COWORK_ORG_LINK_STATES.items()
        }
        unrecognised = len(links) - sum(known_counts.values())
        counts = ", ".join(f"{count} {label.lower()}" for label, count in known_counts.items())
        if unrecognised:
            counts += f", {unrecognised} in an unrecognised state"
        lines += [f"Found {len(links)} organization(s): {counts}.", ""]
        lines += [_format_link_line(link) for link in links]
        lines.append("")
    team_id = result["team_id"]
    lines += [
        f"States: {COWORK_ORG_LINK_STATES_NOTE}",
        "",
        f"Link one with `{LINK_ACTION}(team_id='{team_id}', claude_org_uuid='...')` and "
        f"unlink one with `{UNLINK_ACTION}(team_id='{team_id}', link_id='...')` on "
        "manage_customers; both preview with dry_run=true.",
    ]
    return "\n".join(lines)


def format_link_result_text(result: Dict[str, Any]) -> str:
    team_id = result["team_id"]
    if result.get("dry_run"):
        return "\n".join(
            [
                f"## Dry run - link a Claude organization to team {team_id}",
                "",
                f"Would send: `{result['request']}`",
                "",
                COWORK_ORG_LINK_EFFECT_NOTE,
                "",
                "No request was sent. To apply, repeat the call without dry_run.",
            ]
        )
    lines = [f"## Claude organization linked to team {team_id}", ""]
    link = result.get("link")
    if link:
        lines.append(_format_link_line(link))
    else:
        lines.append(
            "The platform accepted the link but returned no organization; check it with "
            f"`{LIST_ACTION}(team_id='{team_id}')`."
        )
    lines += ["", COWORK_ORG_LINK_EFFECT_NOTE]
    return "\n".join(lines)


def _unlink_target(link: Optional[Dict[str, Any]], link_id: str) -> str:
    if not link:
        return f"link id `{link_id}`"
    target = f"organization `{link['claudeOrgUuid']}` (link id `{link_id}`"
    if link.get("toolName"):
        target += f", shown in Cowork as {_quoted(link['toolName'])}"
    return target + ")"


def format_unlink_result_text(result: Dict[str, Any]) -> str:
    team_id = result["team_id"]
    link_id = result["link_id"]
    link = result.get("link")
    target = _unlink_target(link, link_id)
    if result.get("dry_run"):
        lines = [f"## Dry run - unlink {target} from team {team_id}", ""]
        if result.get("warning"):
            lines += [f"WARNING: {result['warning']}", ""]
        if result.get("warning") and not link:
            lines += [
                "So the listing could not confirm whether this link id exists; the "
                "preview cannot name the organization it routes.",
                "",
            ]
        elif not link:
            lines += [
                f"This link id is not among the team's current links, so the unlink "
                f"would most likely answer not found. Check `{LIST_ACTION}(team_id='{team_id}')`.",
                "",
            ]
        lines += [
            COWORK_ORG_UNLINK_EFFECT_NOTE,
            "",
            "Only the team's links were read; no write was sent. To apply, once the "
            "customer agrees, repeat the call without dry_run:",
            f"`{UNLINK_ACTION}(team_id='{team_id}', link_id='{link_id}')`",
        ]
        return "\n".join(lines)
    return "\n".join(
        [f"## Unlinked {target} from team {team_id}", "", COWORK_ORG_UNLINK_EFFECT_NOTE]
    )


def _raise_cowork_link_error(
    error: ReveniumAPIError,
    team_id: str,
    action: str,
    request: Optional[Dict[str, str]] = None,
    deleted_link_id: Optional[str] = None,
) -> NoReturn:
    """Translate the failures an agent can act on; re-raise the rest."""
    status = error.status_code
    platform_text = error.platform_message
    by_credential = bool(request and "credentialId" in request)
    mode_field = "credential_id" if by_credential else "claude_org_uuid"
    mode_value = (request or {}).get("credentialId" if by_credential else "claudeOrgUuid")
    if status == 403 and "feature not available" in platform_text.lower():
        raise ToolError(
            message="Claude organization links are not enabled for this tenant",
            error_code=ErrorCodes.API_AUTHORIZATION,
            field="action",
            value=action,
            suggestions=[COWORK_ORG_FEATURE_GATE_NOTE, platform_text],
        )
    if status == 403:
        raise ToolError(
            message=(
                f"Insufficient permissions to manage the Claude organization links of "
                f"team {team_id}"
            ),
            error_code=ErrorCodes.API_AUTHORIZATION,
            field="team_id",
            value=team_id,
            suggestions=[
                "Claude organization links require team-management permissions on the "
                "target team",
                "Confirm the API key is scoped to the team you are targeting",
                platform_text,
            ],
        )
    if status == 404 and deleted_link_id is not None:
        raise ToolError(
            message=f"No Claude organization link with that id on team {team_id}, or no such team",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="link_id",
            value=deleted_link_id,
            suggestions=[
                f"Use {LIST_ACTION}(team_id='{team_id}') to see the id of each LINKED organization",
                platform_text,
            ],
        )
    if status == 404:
        suggestions = ["Verify the team ID exists using list(resource_type='teams')"]
        if by_credential:
            suggestions.append(
                "credential_id must be one of this team's own Claude Enterprise credentials"
            )
        raise ToolError(
            message=(
                f"Team {team_id} or the credential named in credential_id was not found"
                if by_credential
                else f"Team not found for id: {team_id}"
            ),
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field="credential_id" if by_credential else "team_id",
            value=mode_value if by_credential else team_id,
            suggestions=[*suggestions, platform_text],
        )
    if status == 409 and action == LINK_ACTION:
        raise ToolError(
            message="This Claude organization cannot be linked from this account",
            error_code=ErrorCodes.RESOURCE_CONFLICT,
            field=mode_field,
            value=mode_value,
            suggestions=[
                "An organization LINKED_BY_ANOTHER_ACCOUNT routes to another account and "
                "is not moved from here",
                f"Use {LIST_ACTION}(team_id='{team_id}') to see each organization's state",
                platform_text,
            ],
        )
    raise error


class CoworkOrgLinkManager:
    """List, link and unlink the Claude organizations whose Cowork activity routes to a team."""

    def __init__(self, client: ReveniumClient) -> None:
        self.client = client

    def _team_id(self, arguments: Dict[str, Any], action: str) -> str:
        return resolve_cowork_team_id(arguments, action, self.client.team_id)

    async def _read_links(self, team_id: str, action: str) -> Dict[str, Any]:
        try:
            response: Any = await self.client.list_team_cowork_org_links(team_id)
        except ReveniumAPIError as e:
            _raise_cowork_link_error(e, team_id, action)

        if not isinstance(response, list):
            return {
                "links": [],
                "warning": (
                    "The platform answered with something other than a list of "
                    "organizations; nothing could be read from it."
                ),
            }
        links = [link for link in map(normalize_cowork_org_link, response) if link]
        skipped = len(response) - len(links)
        result: Dict[str, Any] = {"links": links}
        if skipped:
            result["warning"] = (
                f"{skipped} of {len(response)} entries had no organization uuid and were skipped."
            )
        return result

    async def list_links(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        team_id = self._team_id(arguments, LIST_ACTION)
        read = await self._read_links(team_id, LIST_ACTION)
        return {"action": LIST_ACTION, "team_id": team_id, **read}

    async def link(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        team_id = self._team_id(arguments, LINK_ACTION)
        request = build_link_request(arguments)
        result: Dict[str, Any] = {"action": LINK_ACTION, "team_id": team_id, "request": request}
        if arguments.get("dry_run"):
            return {**result, "dry_run": True}

        try:
            response = await self.client.link_team_cowork_org(team_id, request)
        except ReveniumAPIError as e:
            _raise_cowork_link_error(e, team_id, LINK_ACTION, request)
        return {**result, "link": normalize_cowork_org_link(response)}

    async def unlink(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        team_id = self._team_id(arguments, UNLINK_ACTION)
        link_id = require_link_id(arguments)
        result: Dict[str, Any] = {"action": UNLINK_ACTION, "team_id": team_id, "link_id": link_id}

        if arguments.get("dry_run"):
            read = await self._read_links(team_id, UNLINK_ACTION)
            match = next((link for link in read["links"] if link["linkId"] == link_id), None)
            preview = {**result, "dry_run": True, "link": match}
            if read.get("warning"):
                preview["warning"] = read["warning"]
            return preview

        try:
            await self.client.unlink_team_cowork_org(team_id, link_id)
        except ReveniumAPIError as e:
            _raise_cowork_link_error(e, team_id, UNLINK_ACTION, deleted_link_id=link_id)
        return {**result, "unlinked": True}
