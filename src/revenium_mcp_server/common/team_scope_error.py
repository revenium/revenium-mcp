"""Structured refusal for a read that named a team the credential cannot read.

The analytics host takes an optional ``teamId``; the client sends the team the
session resolved to. A credential that cannot read that team is answered with
403, which the generic 403 guidance reads as a missing permission an
administrator could grant. The fix is a different team or credential instead.

Subclasses both ``ToolError`` (so the tool layer renders the message and
suggestions) and ``ReveniumAPIError`` (so the client's retry loop and every
``except ReveniumAPIError`` caller keep seeing the 403 they already handle).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..client import ReveniumAPIError
from .error_handling import ErrorCodes, ToolError

TEAM_NOT_IN_MEMBERSHIP = "TEAM_NOT_IN_MEMBERSHIP"


class TeamScopeForbiddenError(ToolError, ReveniumAPIError):
    """403 from a read whose ``teamId`` names a team the credential cannot read."""

    def __init__(self, team_id: str, response_data: Optional[Dict[str, Any]] = None):
        ToolError.__init__(
            self,
            message=(
                f"This credential cannot read team {team_id}, so the read was refused (HTTP 403). "
                "An API key answers only for the team it was issued to, and a signed-in user "
                "only for the teams they belong to."
            ),
            error_code=ErrorCodes.API_AUTHORIZATION,
            field="teamId",
            value=team_id,
            suggestions=[
                "Point the session at a team this credential belongs to",
                f"To read team {team_id}, use a credential issued for that team",
            ],
        )
        self.status_code = 403
        self.code = TEAM_NOT_IN_MEMBERSHIP
        self.response_data = response_data
