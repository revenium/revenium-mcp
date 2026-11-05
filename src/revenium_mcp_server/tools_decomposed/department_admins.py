"""Department admins: who is named an admin of a department, and what that lets them see.

A department admin may see the department and every department below it, so
naming one widens what a person can see and removing one narrows it. Both
writes preview with dry_run. The department listing is the only read that
carries admins, so it is what the previews describe and what a removal is
checked against afterwards: the removal answers the same whether or not the
person was an admin.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, NoReturn, Optional, Tuple

from ..client import ReveniumAPIError
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_missing_parameter_error,
    create_structured_validation_error,
)

NAME_ACTION = "name_department_admin"
REMOVE_ACTION = "remove_department_admin"

DEPARTMENT_ADMIN_VISIBILITY_NOTE = (
    "A department admin may see the department and every department below it. Naming "
    "someone an admin widens what they can see in Revenium to that whole subtree; "
    "removing them narrows it again, unless they are also an admin of a department "
    "above it."
)
DEPARTMENT_ADMIN_NAME_EFFECT_NOTE = (
    "The person is looked up by email in the directory; no person is created. Naming "
    "someone who is already an admin changes nothing, except that an admin a CSV "
    "import named becomes named by hand, so undoing that import no longer removes them."
)
DEPARTMENT_ADMIN_REMOVE_EFFECT_NOTE = (
    "The platform answers a removal the same way whether or not the person was an "
    "admin, so the answer re-reads the department's admins and says whether the "
    "person is still listed."
)
DEPARTMENT_ADMIN_PREVIEW_NOTE = (
    "Both run when called. Preview first with dry_run=true, which reads the "
    "departments to name the subtree the person would gain or lose and sends no "
    "write, and run them only after the customer agrees to the change in access."
)
DEPARTMENT_ADMIN_ID_NOTE = (
    "department_id is the numeric id list_departments returns; person_id is the "
    "directory person id of an admin, shown by the remove_department_admin preview."
)


@dataclass(frozen=True)
class DepartmentAdmin:
    person_id: Optional[int]
    email: Optional[str]
    has_login: Optional[bool]
    source: Optional[str]

    def matches(self, person_id: Optional[int], email: Optional[str]) -> bool:
        if person_id is not None:
            return self.person_id == person_id
        return bool(email and self.email and self.email.casefold() == email.casefold())

    def describe(self) -> str:
        who = self.email or "(no email on record)"
        details = [f"person_id {self.person_id}" if self.person_id is not None else "no person_id"]
        if self.source:
            details.append(f"named {self.source}")
        if self.has_login is False:
            details.append("no Revenium login yet")
        return f"{who} ({', '.join(details)})"


@dataclass(frozen=True)
class DepartmentNode:
    id: int
    name: str
    path_ids: Tuple[int, ...]
    admins: Optional[Tuple[DepartmentAdmin, ...]]

    def admin(self, person_id: Optional[int], email: Optional[str]) -> Optional[DepartmentAdmin]:
        return next((a for a in self.admins or () if a.matches(person_id, email)), None)


def department_entry_id(value: Any) -> Optional[int]:
    """The id of a department listing entry, or None when the entry is malformed.

    The one rule both the department listing and the admin actions use to skip an entry.
    """
    unit_id = _as_int(value)
    return unit_id if unit_id is not None and unit_id >= 0 else None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    return None


def normalize_admin(raw: Any) -> Optional[DepartmentAdmin]:
    if not isinstance(raw, dict):
        return None
    email = raw.get("email")
    has_login = raw.get("hasLogin")
    source = raw.get("source")
    return DepartmentAdmin(
        person_id=_as_int(raw.get("personId")),
        email=email.strip() if isinstance(email, str) and email.strip() else None,
        has_login=has_login if isinstance(has_login, bool) else None,
        source=source if isinstance(source, str) else None,
    )


def normalize_admins(raw: Any) -> List[DepartmentAdmin]:
    if not isinstance(raw, list):
        return []
    return [admin for admin in map(normalize_admin, raw) if admin]


def _path_ids(path: Any, unit_id: int) -> Tuple[int, ...]:
    if isinstance(path, str):
        ids = tuple(i for i in (_as_int(part) for part in path.split("/") if part) if i is not None)
        if ids and ids[-1] == unit_id:
            return ids
    return (unit_id,)


class DepartmentTree:
    """The team's departments as the listing returns them, indexed for subtree questions."""

    def __init__(
        self, nodes: Dict[int, DepartmentNode], readable: bool = True, skipped: int = 0
    ) -> None:
        self._nodes = nodes
        self.readable = readable
        self.skipped = skipped

    @classmethod
    def from_response(cls, response: Any) -> "DepartmentTree":
        if not isinstance(response, list):
            return cls({}, readable=False)
        nodes: Dict[int, DepartmentNode] = {}
        for raw in response:
            unit_id = department_entry_id(raw.get("id")) if isinstance(raw, dict) else None
            if unit_id is None:
                continue
            name = raw.get("name")
            nodes[unit_id] = DepartmentNode(
                id=unit_id,
                name=name if isinstance(name, str) and name.strip() else f"#{unit_id}",
                path_ids=_path_ids(raw.get("path"), unit_id),
                admins=(
                    tuple(normalize_admins(raw["admins"]))
                    if isinstance(raw.get("admins"), list)
                    else None
                ),
            )
        skipped = len(response) - len(nodes)
        return cls(nodes, readable=bool(nodes) or not response, skipped=skipped)

    @property
    def problem(self) -> Optional[str]:
        """Why the listing cannot be trusted to be complete, or None when it can."""
        if not self.readable and self.skipped:
            return (
                f"All {self.skipped} entries in the departments listing were malformed, so the "
                "department, its subtree and its admins could not be read. This is an upstream "
                "data or contract problem, not a team without departments."
            )
        if not self.readable:
            return (
                "The departments listing answered with something other than a list, so the "
                "department, its subtree and its admins could not be read."
            )
        if self.skipped:
            return (
                f"{self.skipped} malformed entries in the departments listing were skipped, so "
                "the departments below and the admin namings shown may be incomplete."
            )
        return None

    def get(self, department_id: int) -> Optional[DepartmentNode]:
        return self._nodes.get(department_id)

    def label(self, node: DepartmentNode) -> str:
        names = [self._nodes[i].name if i in self._nodes else f"#{i}" for i in node.path_ids]
        return f"{' / '.join(names)} (id {node.id})"

    def descendants(self, department_id: int) -> List[DepartmentNode]:
        below = [
            node
            for node in self._nodes.values()
            if node.id != department_id and department_id in node.path_ids
        ]
        return sorted(below, key=self.label)

    def access_after_removal(
        self, node: DepartmentNode, person_id: Optional[int], email: Optional[str]
    ) -> Dict[str, List[str]]:
        """Split the department's subtree into what the person loses and what another naming keeps."""
        other_namings = [
            n for n in self._nodes.values() if n.id != node.id and n.admin(person_id, email)
        ]
        other_ids = {n.id for n in other_namings}
        subtree = [node, *self.descendants(node.id)]
        kept = [n for n in subtree if other_ids.intersection(n.path_ids)]
        kept_ids = {n.id for n in kept}
        covering = [n for n in other_namings if any(n.id in k.path_ids for k in kept)]
        return {
            "loses": [self.label(n) for n in subtree if n.id not in kept_ids],
            "keeps": [self.label(n) for n in kept],
            "kept_through": sorted(self.label(n) for n in covering),
        }

    def ancestors_administered_by(
        self, node: DepartmentNode, person_id: Optional[int], email: Optional[str]
    ) -> List[DepartmentNode]:
        ancestors = (self._nodes.get(i) for i in node.path_ids[:-1])
        return [a for a in ancestors if a is not None and a.admin(person_id, email)]


def validate_department_id(value: Any, action: str) -> int:
    """Accept the raw numeric department id as a positive int or a digit string."""
    if value is None:
        raise create_structured_missing_parameter_error(
            parameter_name="department_id",
            action=action,
            examples={
                "usage": f"{action}(department_id=173, ...)",
                "discover_ids": "list_departments() on get_customers - the id of each department",
            },
        )
    department_id = _as_int(value)
    if department_id is None or department_id <= 0:
        raise create_structured_validation_error(
            message=f"Invalid department_id: {value!r}",
            field="department_id",
            value=value,
            suggestions=[DEPARTMENT_ADMIN_ID_NOTE],
            examples={"usage": f"{action}(department_id=173, ...)"},
        )
    return department_id


def unknown_department_error(team_id: Optional[str], department_id: int) -> ToolError:
    return ToolError(
        message=f"Department {department_id} is not among the team's active departments",
        error_code=ErrorCodes.RESOURCE_NOT_FOUND,
        field="department_id",
        value=department_id,
        suggestions=[
            "No request was sent",
            f"Use list_departments({_team_argument(team_id)}) to find the department's id",
        ],
    )


def resolve_admin_person_id(
    tree: DepartmentTree, team_id: Optional[str], department_id: int, email: str
) -> int:
    """The person_id the removal route needs, from the department's admin with this email."""
    node = tree.get(department_id)
    if node is None:
        raise ToolError(
            message="The departments could not be read, so the email cannot be resolved to an admin",
            error_code=ErrorCodes.API_ERROR,
            field="email",
            value=email,
            suggestions=[
                "No request was sent",
                f"Pass person_id instead: {REMOVE_ACTION}(department_id={department_id}, person_id=97)",
            ],
        )
    if node.admins is None:
        raise ToolError(
            message=f"The listing carried no admins for department {department_id}, so the email cannot be resolved",
            error_code=ErrorCodes.API_ERROR,
            field="email",
            value=email,
            suggestions=[
                "No request was sent",
                f"Pass person_id instead: {REMOVE_ACTION}(department_id={department_id}, person_id=97)",
            ],
        )
    admin = node.admin(None, email)
    if admin is None or admin.person_id is None:
        raise _not_an_admin_error(tree, node, team_id, email)
    return admin.person_id


PRIMARY_EMAIL_NOTE = (
    "The listing shows each admin's primary email only; a person reached through "
    "another of their addresses is not matched by it. Use person_id from the admins "
    "listed here instead."
)


def _not_an_admin_error(
    tree: DepartmentTree, node: DepartmentNode, team_id: Optional[str], email: str
) -> ToolError:
    admins = "; ".join(a.describe() for a in node.admins or ()) or "none"
    return ToolError(
        message=f"No admin of {tree.label(node)} is listed with the email {email}",
        error_code=ErrorCodes.RESOURCE_NOT_FOUND,
        field="email",
        value=email,
        suggestions=[
            "No request was sent",
            f"Current admins: {admins}",
            PRIMARY_EMAIL_NOTE,
            f"Preview with {REMOVE_ACTION}(department_id={node.id}, dry_run=true{_team_suffix(team_id)})",
        ],
    )


def raise_department_admin_error(
    error: ReveniumAPIError,
    action: str,
    team_id: Optional[str],
    department_id: int,
    *,
    email: Optional[str] = None,
    person_id: Optional[int] = None,
) -> NoReturn:
    """Translate the admin routes' documented 400/404/409/422 answers; re-raise the rest."""
    upstream = error.platform_message
    person_field, person_value = ("email", email) if email is not None else ("person_id", person_id)
    status = error.status_code
    if status == 404:
        names_person = action == NAME_ACTION and any(
            word in upstream.lower() for word in ("person", "email")
        )
        raise ToolError(
            message=f"Not found: {upstream}",
            error_code=ErrorCodes.RESOURCE_NOT_FOUND,
            field=person_field if names_person else "department_id",
            value=person_value if names_person else department_id,
            suggestions=[
                "The email must belong to a person in the team's directory"
                if names_person
                else "The department may have been deleted, or belong to another team",
                f"Use list_departments({_team_argument(team_id)}) to check the department id",
            ],
        )
    if status == 409:
        raise ToolError(
            message=f"The platform refused to change the admins of department {department_id} (409): {upstream}",
            error_code=ErrorCodes.RESOURCE_CONFLICT,
            field=person_field,
            value=person_value,
            suggestions=[
                "Nothing was changed. The platform reports a conflict with an existing "
                "record; read the department's current admins before retrying",
                f"Preview with {action}(department_id={department_id}, dry_run=true{_team_suffix(team_id)}, ...) "
                "to see the department's current admins",
            ],
        )
    if status in (400, 422):
        raise ToolError(
            message=f"The platform rejected the request ({status}): {upstream}",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field=person_field,
            value=person_value,
            suggestions=[
                "An email that matches more than one directory person is rejected; "
                "the person must be unique in the directory"
                if action == NAME_ACTION
                else DEPARTMENT_ADMIN_ID_NOTE,
            ],
        )
    raise error


def _team_argument(team_id: Optional[str]) -> str:
    return f"team_id='{team_id}'" if team_id else ""


def _team_suffix(team_id: Optional[str]) -> str:
    return f", team_id='{team_id}'" if team_id else ""


def _scope(team_id: Optional[str]) -> str:
    return f"team {team_id}" if team_id else "the ambient team"


def _admins_payload(admins: Any) -> Optional[List[Dict[str, Any]]]:
    return None if admins is None else [asdict(a) for a in admins]


def describe_department(tree: DepartmentTree, node: Optional[DepartmentNode]) -> Optional[Dict[str, Any]]:
    if node is None:
        return None
    return {
        "id": node.id,
        "label": tree.label(node),
        "departments_below": [tree.label(below) for below in tree.descendants(node.id)],
        "admins": _admins_payload(node.admins),
    }


def name_preview(
    tree: DepartmentTree,
    team_id: Optional[str],
    department_id: int,
    email: str,
) -> Dict[str, Any]:
    node = tree.get(department_id)
    result = _base_result(NAME_ACTION, team_id, department_id, tree, node)
    result.update({"email": email, "dry_run": True, "request": {"email": email}})
    if node is not None:
        existing = node.admin(None, email)
        result["already_admin"] = asdict(existing) if existing else None
        result["admin_above"] = [tree.label(a) for a in tree.ancestors_administered_by(node, None, email)]
    return result


def remove_preview(
    tree: DepartmentTree,
    team_id: Optional[str],
    department_id: int,
    person_id: Optional[int],
    email: Optional[str],
) -> Dict[str, Any]:
    node = tree.get(department_id)
    result = _base_result(REMOVE_ACTION, team_id, department_id, tree, node)
    result.update({"person_id": person_id, "email": email, "dry_run": True})
    if node is not None:
        target = node.admin(person_id, email)
        result["target_admin"] = asdict(target) if target else None
        result["access_after"] = tree.access_after_removal(node, person_id, email)
    return result


def _base_result(
    action: str,
    team_id: Optional[str],
    department_id: int,
    tree: DepartmentTree,
    node: Optional[DepartmentNode],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "action": action,
        "resource_type": "department_admins",
        "team_id": team_id,
        "department_id": department_id,
        "department": describe_department(tree, node),
    }
    if tree.problem:
        result["warning"] = tree.problem
    return result


def name_result(
    tree: DepartmentTree,
    team_id: Optional[str],
    department_id: int,
    email: str,
    response: Any,
) -> Dict[str, Any]:
    node = tree.get(department_id)
    before = node.admin(None, email) if node else None
    admins_after = normalize_admins(response)
    after = next((a for a in admins_after if a.matches(None, email)), None)
    added = _added_admins(node, admins_after)
    was_admin_before = before is not None or (after is None and added == [] and bool(admins_after))
    result = _base_result(NAME_ACTION, team_id, department_id, tree, node)
    result.update(
        {
            "email": email,
            "was_admin_before": was_admin_before,
            "matched_by_email": before is not None or after is not None,
            "named_admin": asdict(after) if after else None,
            "admins_added": _admins_payload(added),
            "admins_after": _admins_payload(admins_after),
        }
    )
    if before is not None and after is not None and before.source == "CSV" and after.source == "MANUAL":
        result["source_changed"] = "CSV -> MANUAL"
    return result


def _added_admins(
    node: Optional[DepartmentNode], admins_after: List[DepartmentAdmin]
) -> Optional[List[DepartmentAdmin]]:
    """Admins the PUT returned that the listing did not have, or None when there is no listing to compare."""
    if node is None or node.admins is None:
        return None
    before_ids = {a.person_id for a in node.admins}
    return [a for a in admins_after if a.person_id not in before_ids]


def remove_result(
    before_tree: DepartmentTree,
    after_tree: Optional[DepartmentTree],
    team_id: Optional[str],
    department_id: int,
    person_id: int,
    email: Optional[str],
    reread_error: Optional[str] = None,
) -> Dict[str, Any]:
    node = before_tree.get(department_id)
    before = node.admin(person_id, None) if node else None
    result = _base_result(REMOVE_ACTION, team_id, department_id, before_tree, node)
    result.update(
        {
            "person_id": person_id,
            "email": email or (before.email if before else None),
            "request_sent": True,
            "was_admin_before": None if node is None or node.admins is None else before is not None,
        }
    )
    after_node = after_tree.get(department_id) if after_tree and after_tree.readable else None
    reread_problem = reread_error or _reread_problem(after_tree, department_id)
    if after_tree is None or after_node is None or after_node.admins is None or reread_problem:
        result["still_admin"] = None
        result["reread_problem"] = reread_problem
        return result
    result["still_admin"] = after_node.admin(person_id, None) is not None
    result["admins_after"] = _admins_payload(after_node.admins)
    result["access_after"] = after_tree.access_after_removal(after_node, person_id, None)
    return result


def _reread_problem(after_tree: Optional[DepartmentTree], department_id: int) -> Optional[str]:
    if after_tree is None:
        return None
    if not after_tree.readable:
        return after_tree.problem
    node = after_tree.get(department_id)
    if node is None:
        return "The listing read after the removal no longer contains the department"
    if node.admins is None:
        return "The listing read after the removal did not carry this department's admins"
    return None


def _subtree_lines(department: Dict[str, Any], verb: str) -> List[str]:
    below = department["departments_below"]
    if not below:
        return [f"{verb} {department['label']}. It has no departments below it."]
    return [f"{verb} {department['label']} and the {len(below)} department(s) below it:"] + [
        f"- {label}" for label in below
    ]


def _kept_lines(who: str, access: Dict[str, List[str]], verb: str) -> List[str]:
    return [
        f"{who} {verb} these through their admin naming on {', '.join(access['kept_through'])}:",
        *[f"- {label}" for label in access["keeps"]],
        "",
    ]


def _access_lines(who: str, access: Dict[str, List[str]], lose_verb: str, keep_verb: str) -> List[str]:
    lines: List[str] = []
    if access["loses"]:
        lines += [f"{who} {lose_verb}:", *[f"- {label}" for label in access["loses"]], ""]
    else:
        lines += [f"{who} would lose nothing they can see.", ""]
    if access["keeps"]:
        lines += _kept_lines(who, access, keep_verb)
    return lines


def _admin_lines(admins: Optional[List[Dict[str, Any]]]) -> List[str]:
    if admins is None:
        return ["- could not be read: the listing carried no admins for this department"]
    if not admins:
        return ["- none"]
    return [f"- {DepartmentAdmin(**a).describe()}" for a in admins]


def _with_warning(lines: List[str], result: Dict[str, Any]) -> List[str]:
    if result.get("warning"):
        return [*lines[:2], f"WARNING: {result['warning']}", "", *lines[2:]]
    return lines


def _missing_department_lines(result: Dict[str, Any], outcome: str) -> List[str]:
    if result.get("warning"):
        return []
    return [
        f"Department {result['department_id']} is not among the team's active departments, "
        f"so the call would {outcome}. Check `list_departments({_team_argument(result['team_id'])})`.",
        "",
    ]


def format_name_admin_text(result: Dict[str, Any]) -> str:
    email = result["email"]
    department = result["department"]
    scope = _scope(result["team_id"])
    target = department["label"] if department else f"department {result['department_id']}"
    if result.get("dry_run"):
        lines = [f"## Dry run - name {email} an admin of {target} in {scope}", ""]
        if department is None:
            lines += _missing_department_lines(result, "answer not found")
        else:
            already = result.get("already_admin")
            if already:
                lines += [
                    f"{email} is already an admin of this department "
                    f"(named {already.get('source') or 'unknown'}). Naming them again grants "
                    "nothing new"
                    + (
                        "; it only turns the CSV naming into a naming by hand."
                        if already.get("source") == "CSV"
                        else "."
                    ),
                    "",
                ]
            lines += _subtree_lines(department, f"Once named, {email} will be able to see")
            lines.append("")
            if result.get("admin_above"):
                lines += [
                    f"{email} is already an admin of {', '.join(result['admin_above'])}, "
                    "so they can already see this subtree.",
                    "",
                ]
            lines += ["Current admins of this department:", *_admin_lines(department["admins"]), ""]
        lines += [
            f"Would send: PUT /v2/api/departments/{result['department_id']}/admins with `{json.dumps(result['request'])}`",
            "",
            DEPARTMENT_ADMIN_NAME_EFFECT_NOTE,
            "",
            "Only the departments were read; no write was sent. To apply, once the "
            "customer agrees, repeat the call without dry_run:",
            f"`{NAME_ACTION}(department_id={result['department_id']}, email='{email}'{_team_suffix(result['team_id'])})`",
        ]
        return "\n".join(_with_warning(lines, result))

    named = result.get("named_admin")
    if result.get("was_admin_before"):
        lines = [f"## {email} was already an admin of {target}; nothing new was granted", ""]
        if not result.get("matched_by_email"):
            lines += [
                f"No admin is listed under {email}, but the platform added no one, so the "
                "address most likely belongs to an existing admin listed under their "
                "primary email.",
                "",
            ]
        if result.get("source_changed"):
            lines += [
                "The platform turned the CSV naming into a naming by hand, so undoing that "
                "CSV import no longer removes them.",
                "",
            ]
    elif named:
        lines = [f"## Named {email} an admin of {target} in {scope}", ""]
        if department:
            lines += _subtree_lines(department, f"{email} can now see")
            lines.append("")
        if named.get("has_login") is False:
            lines += [
                f"{email} has no Revenium login yet; the access applies once they can sign in.",
                "",
            ]
    else:
        lines = [
            f"## The platform accepted the naming, but {email} is not among the admins it returned",
            "",
        ]
        if result.get("admins_added"):
            lines += [
                "Admins listed now that were not listed before the call:",
                *_admin_lines(result["admins_added"]),
                "",
                f"If {email} is another address of one of them, the naming is done. The "
                "listing alone cannot tell, because another naming may have landed between "
                "the read and this call, so the grant is left unconfirmed here.",
                "",
            ]
        lines += [
            f"Check with `{NAME_ACTION}(department_id={result['department_id']}, email='{email}', "
            f"dry_run=true{_team_suffix(result['team_id'])})`. {PRIMARY_EMAIL_NOTE}",
            "",
        ]
    lines += ["Admins of this department now:", *_admin_lines(result["admins_after"])]
    return "\n".join(_with_warning(lines, result))


def format_remove_admin_text(result: Dict[str, Any]) -> str:
    department = result["department"]
    scope = _scope(result["team_id"])
    target = department["label"] if department else f"department {result['department_id']}"
    who = result.get("email") or (result.get("target_admin") or {}).get("email") or f"person {result['person_id']}"
    if result.get("dry_run"):
        lines = [f"## Dry run - remove {who} as an admin of {target} in {scope}", ""]
        if department is None:
            lines += _missing_department_lines(result, "answer not found")
        else:
            target_admin = result.get("target_admin")
            if department["admins"] is None:
                lines += [
                    f"The listing carried no admins for this department, so whether {who} "
                    "is an admin, and what they would stop seeing, cannot be told.",
                    "",
                ]
            elif target_admin is None:
                lines += [
                    f"{who} is not among this department's admins, so the removal would "
                    "change nothing (the platform answers the same either way).",
                    "",
                ]
                if result.get("person_id") is None:
                    lines += [PRIMARY_EMAIL_NOTE, ""]
            else:
                lines += [f"Admin to remove: {DepartmentAdmin(**target_admin).describe()}", ""]
                if target_admin.get("source") == "SYNCED":
                    lines += [
                        "This admin was named by directory sync, which may name them again.",
                        "",
                    ]
            if target_admin:
                lines += _access_lines(who, result["access_after"], "would stop seeing", "would keep seeing")
            lines += ["Current admins of this department:", *_admin_lines(department["admins"]), ""]
        identifier = (
            f"person_id={result['person_id']}"
            if result.get("person_id") is not None
            else f"email='{result['email']}'"
        )
        lines += [
            DEPARTMENT_ADMIN_REMOVE_EFFECT_NOTE,
            "",
            "Only the departments were read; no write was sent. To apply, once the "
            "customer agrees, repeat the call without dry_run:",
            f"`{REMOVE_ACTION}(department_id={result['department_id']}, {identifier}{_team_suffix(result['team_id'])})`",
        ]
        return "\n".join(_with_warning(lines, result))

    still = result.get("still_admin")
    if still is None:
        lines = [
            f"## Sent the removal of {who} as an admin of {target}, but could not confirm it",
            "",
            f"The platform accepted it, but the admins could not be re-read: {result['reread_problem']}",
            f"Check with `{REMOVE_ACTION}(department_id={result['department_id']}, "
            f"person_id={result['person_id']}, dry_run=true{_team_suffix(result['team_id'])})`.",
        ]
        return "\n".join(_with_warning(lines, result))
    if still:
        headline = (
            f"## WARNING: {who} is still listed as an admin of {target} after the removal"
        )
    elif result.get("was_admin_before"):
        headline = f"## Removed {who} as an admin of {target}; they are no longer listed"
    elif result.get("was_admin_before") is None:
        headline = (
            f"## {who} is not listed as an admin of {target} now; whether they were before "
            "could not be read"
        )
    else:
        headline = (
            f"## {who} was not an admin of {target}; nothing changed, and they are not listed now"
        )
    lines = [headline, ""]
    if not still and result["access_after"]["keeps"]:
        lines += _kept_lines(who, result["access_after"], "still sees")
    lines += ["Admins of this department now (re-read after the call):", *_admin_lines(result["admins_after"])]
    return "\n".join(_with_warning(lines, result))
