"""The PR-health settings fields beyond the aging/rotting threshold pair.

Each writable field is declared once in PR_HEALTH_OPTIONAL_FIELDS: the tool
argument, the wire name and the local validation that mirrors the limits the
platform documents on PrHealthSettingsResource.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Tuple

from ..common.error_handling import ToolError, create_structured_validation_error

PR_HEALTH_MIN_CUTOFF_DATE = date(2008, 1, 1)
PR_HEALTH_MAX_EXCLUDED_REPOS = 200
PR_HEALTH_MAX_AUTOMATION_PATTERNS = 20
PR_HEALTH_MAX_AUTOMATION_PATTERN_LENGTH = 200

# The character set the platform's 400 names for an excludedRepos entry.
PR_HEALTH_REPO_PATTERN = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

# Every stored or derived field a read renders beside the threshold pair, in the
# order the API declares them. builtInAutomationPatterns, cutoffDateIsDefault and
# defaultCutoffDate are echoes the tool never sends back.
PR_HEALTH_DISPLAY_FIELDS = (
    "assistedOnly",
    "automationPatterns",
    "builtInAutomationPatterns",
    "cutoffDate",
    "cutoffDateIsDefault",
    "defaultCutoffDate",
    "excludedRepos",
)

PR_HEALTH_FIELDS_NOTE = (
    "cutoffDate is the effective cutoff - pull requests opened before it are left out of "
    "every PR-health figure: the team's own date, else the organization's first "
    "AI-telemetry day (cutoffDateIsDefault true, also shown as defaultCutoffDate), else "
    "null for no cutoff. excludedRepos (owner/repo) are left out of every figure. "
    "automationPatterns are the team's custom regular expressions, applied beside the "
    "read-only builtInAutomationPatterns, that put a matching pull request in the "
    "automation bucket. assistedOnly is the team default for pricing and listing "
    "AI-assisted pull requests only."
)

PR_HEALTH_OMITTED_FIELDS_NOTE = (
    "Fields omitted from an update (assisted_only, automation_patterns, cutoff_date, "
    "excluded_repos) are left unchanged by the platform, so only the ones you name are "
    "sent. A supplied automation_patterns or excluded_repos list replaces the stored one "
    "(include the current entries to keep them) and an empty list clears it. The "
    "agingDays/rottingDays pair is the exception: the API requires both, so the one you "
    "leave out is read-merged from the current settings."
)

_USAGE_EXAMPLE = (
    "update_pr_health_settings(team_id='jR2kmLs', excluded_repos=['acme/legacy-app'], "
    "cutoff_date='2025-03-01')"
)


def _invalid(snake: str, value: Any, problem: str, suggestions: List[str]) -> ToolError:
    return create_structured_validation_error(
        message=f"{snake} {problem}",
        field=snake,
        value=value,
        suggestions=suggestions,
        examples={"usage": _USAGE_EXAMPLE},
    )


def _validate_assisted_only(value: Any, snake: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid(snake, value, "must be true or false", ["Pass assisted_only=true or assisted_only=false"])
    return value


def _validate_cutoff_date(value: Any, snake: str) -> str:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        raise _invalid(snake, value, "must be a date in yyyy-MM-dd format", ["Example: cutoff_date='2025-03-01'"])
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _invalid(snake, value, "is not a real calendar date", ["Example: cutoff_date='2025-03-01'"]) from None
    today_utc = datetime.now(timezone.utc).date()
    if parsed > today_utc:
        raise _invalid(
            snake, value, "must not be in the future",
            [f"Pick today (UTC, {today_utc.isoformat()}) or an earlier date"],
        )
    if parsed < PR_HEALTH_MIN_CUTOFF_DATE:
        raise _invalid(
            snake, value, f"must be on or after {PR_HEALTH_MIN_CUTOFF_DATE.isoformat()}",
            ["The platform rejects earlier cutoff dates"],
        )
    return value


def _validate_string_list(value: Any, snake: str, max_items: int) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _invalid(
            snake, value, "must be a list of strings",
            [f"Pass a JSON array, e.g. {snake}=[...]; an empty list clears the stored value"],
        )
    if len(value) > max_items:
        raise _invalid(snake, value, f"accepts at most {max_items} entries (got {len(value)})", [])
    return value


def _validate_excluded_repos(value: Any, snake: str) -> List[str]:
    repos = _validate_string_list(value, snake, PR_HEALTH_MAX_EXCLUDED_REPOS)
    malformed = [repo for repo in repos if not PR_HEALTH_REPO_PATTERN.fullmatch(repo)]
    if malformed:
        raise _invalid(
            snake, value, f"entries must be shaped owner/repo: {', '.join(malformed)}",
            ["Use letters, digits, dots, hyphens and underscores, e.g. 'acme/legacy-app'"],
        )
    return repos


def _validate_automation_patterns(value: Any, snake: str) -> List[str]:
    patterns = _validate_string_list(value, snake, PR_HEALTH_MAX_AUTOMATION_PATTERNS)
    if any(not pattern.strip() for pattern in patterns):
        raise _invalid(snake, value, "entries must be non-empty strings", [])
    too_long = [p for p in patterns if len(p) > PR_HEALTH_MAX_AUTOMATION_PATTERN_LENGTH]
    if too_long:
        raise _invalid(
            snake, value,
            f"entries must be at most {PR_HEALTH_MAX_AUTOMATION_PATTERN_LENGTH} characters",
            [],
        )
    matches_empty = [p for p in patterns if _matches_empty_string(p)]
    if matches_empty:
        raise _invalid(
            snake, value,
            f"entries must not match an empty string: {', '.join(matches_empty)}",
            ["A pattern that matches an empty string would mark every pull request as automation"],
        )
    return patterns


def _matches_empty_string(pattern: str) -> bool:
    # Best effort: the platform validates with Java and PostgreSQL regex engines, so a
    # pattern Python cannot compile may still be valid there and is left to the server.
    try:
        return re.fullmatch(pattern, "") is not None
    except re.error:
        return False


@dataclass(frozen=True)
class PrHealthOptionalField:
    """One writable PR-health field the platform leaves unchanged when omitted."""

    snake: str
    camel: str
    validate: Callable[[Any, str], Any]
    description: str
    comparable: Callable[[Any], Any] = lambda value: value


def _as_repo_set(value: Any) -> Any:
    # The platform matches repositories case-insensitively and echoes them sorted, so
    # a re-ordered or re-cased echo is the same stored list, not a lost update.
    if not isinstance(value, list):
        return value
    return sorted(repo.lower() if isinstance(repo, str) else repo for repo in value)


PR_HEALTH_OPTIONAL_FIELDS: Tuple[PrHealthOptionalField, ...] = (
    PrHealthOptionalField(
        "assisted_only", "assistedOnly", _validate_assisted_only,
        "bool (optional) - team default for pricing and listing AI-assisted pull requests only",
    ),
    PrHealthOptionalField(
        "automation_patterns", "automationPatterns", _validate_automation_patterns,
        f"list[str] (optional, at most {PR_HEALTH_MAX_AUTOMATION_PATTERNS}, each at most "
        f"{PR_HEALTH_MAX_AUTOMATION_PATTERN_LENGTH} characters) - custom regular expressions "
        "matched against PR title and author; replaces the stored list, [] clears it",
    ),
    PrHealthOptionalField(
        "cutoff_date", "cutoffDate", _validate_cutoff_date,
        f"str yyyy-MM-dd (optional, {PR_HEALTH_MIN_CUTOFF_DATE.isoformat()} to today UTC) - "
        "pull requests opened earlier are left out of every figure",
    ),
    PrHealthOptionalField(
        "excluded_repos", "excludedRepos", _validate_excluded_repos,
        f"list[str] owner/repo (optional, at most {PR_HEALTH_MAX_EXCLUDED_REPOS}) - "
        "repositories left out of every figure; replaces the stored list, [] clears it",
        _as_repo_set,
    ),
)


def collect_optional_updates(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the optional fields the caller supplied, keyed by wire name."""
    return {
        spec.camel: spec.validate(arguments[spec.snake], spec.snake)
        for spec in PR_HEALTH_OPTIONAL_FIELDS
        if arguments.get(spec.snake) is not None
    }


def diverged_optional_fields(sent: Dict[str, Any], stored: Any) -> Dict[str, Dict[str, Any]]:
    """Sent optional fields whose echoed value differs, as {camel: {sent, stored}}.

    An echo that omits a field is unknown rather than changed, so it is not divergence.
    """
    payload = stored if isinstance(stored, dict) else {}
    return {
        spec.camel: {"sent": sent[spec.camel], "stored": payload[spec.camel]}
        for spec in PR_HEALTH_OPTIONAL_FIELDS
        if spec.camel in sent
        and spec.camel in payload
        and spec.comparable(payload[spec.camel]) != spec.comparable(sent[spec.camel])
    }


def present_display_fields(settings: Any) -> Dict[str, Any]:
    """The display fields a settings payload actually carries, absent ones omitted."""
    payload = settings if isinstance(settings, dict) else {}
    return {camel: payload[camel] for camel in PR_HEALTH_DISPLAY_FIELDS if camel in payload}
