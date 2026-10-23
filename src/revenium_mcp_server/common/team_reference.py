"""A team a create names inside its data, sent as the teamId the platform reads.

The platform files a new record under the body's teamId and ignores a `team`
field, so a team given only as `team` used to be replaced by the configured
team without a word.
"""

from typing import Any, Dict

from .error_handling import create_structured_validation_error
from .partial_update_handler import FieldTransformers

_TEAM_FIELDS = ("team", "teamId")


def _names_no_team(value: Any) -> bool:
    return value is None or value == ""


def with_team_reference_as_team_id(data: Dict[str, Any], argument: str) -> Dict[str, Any]:
    """Return a copy of data whose `team` (an id or an object with one) is its teamId.

    A null or empty `team` or `teamId` names no team and is left out, so the
    configured team applies. Refuses a `team` that names no id, and one that
    disagrees with a teamId sent beside it, instead of choosing between them.
    """
    folded = {key: value for key, value in data.items() if key not in _TEAM_FIELDS}
    team = data.get("team")
    stated_team_id = data.get("teamId")
    if not _names_no_team(stated_team_id):
        folded["teamId"] = stated_team_id
    if _names_no_team(team):
        return folded
    team_id = FieldTransformers.reference_to_id(team)
    if team_id is None:
        raise create_structured_validation_error(
            message=(
                f"{argument}.team names no team id, so nothing was created; "
                "send the team's id"
            ),
            field=f"{argument}.team",
            value=team,
            suggestions=[f"Send {argument}.teamId with the team's id, or leave both out"],
        )
    if not _names_no_team(stated_team_id) and stated_team_id != team_id:
        raise create_structured_validation_error(
            message=(
                f"{argument}.team ({team_id}) and {argument}.teamId ({stated_team_id}) "
                "name different teams, so nothing was created"
            ),
            field=f"{argument}.teamId",
            value=stated_team_id,
            suggestions=[f"Send one team, as {argument}.teamId"],
        )
    folded["teamId"] = team_id
    return folded
