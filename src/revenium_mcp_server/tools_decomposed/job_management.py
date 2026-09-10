"""Job management tool for Revenium Jobs & Outcomes system.

Exposes 7 API endpoints under /v2/api/jobs for tracking job performance,
ROI, conversion funnels, and reporting outcomes, plus the read side of
coding-session ticket attribution
(GET /v2/api/sessions/{sessionId}/attribution) — the write that produces the
ticket-grain jobs this tool already reads. get_roi_summary is the one
action that leaves that family: it reads the analytics host's published
job-type ROI summary (BACK-2915) instead of aggregating funnels here.

Decision (BACK-2769): the MCP exposes the READ half of session attribution as
``list_session_attributions`` and deliberately does NOT expose the write half,
POST /v2/api/sessions/{sessionId}/attribution. Two reasons, both standing:

1. The write already has a shipped owner, on the plane the endpoint was
   designed for. The ticket-gate CLI (``src/claude-code/ticket/
   association-client.ts`` in revenium-cli-node-internal, anchors
   ``buildAssociationUrl`` / ``postAssociation``) POSTs the attribution from
   the developer machine with a fleet-distributed METERING-scoped API key,
   where the platform resolves ``teamId`` from the key itself and writes are
   append-only. Adding a second writer here would re-implement a working path
   on the management plane, which is not the plane it was built for.
2. An MCP model has no reliable source for its own coding-session UUID. The
   CLI reads it from the Claude Code hook payload; an MCP tool would have to
   ask the model to supply an identifier it cannot observe, and no session
   listing or discovery endpoint exists to look it up. Revisit this decision
   when such a source appears — not merely because the endpoint shows up
   again in the next drift run.

Write-side error semantics, recorded here so they are not re-derived if that
day comes: 422 UnprocessableEntityException covers ticketId/splits
exclusivity, a split member count outside 1-10, weight problems, duplicate
members, title validation, and an ``effectiveFrom`` in the future. 400 covers
only the scalar ``ticketId`` pattern violation (plus the literal ``none``
unlink value) and a ``source`` outside the CodingAssistantSource enum
(claude-code, gemini-cli, codex, cursor, copilot, other — free-form strings
are rejected). Splits are additionally gated behind the
``coding-assistant-splits-enabled`` feature flag, and weights are normalized
server-side, so a client must surface the server's rejection rather than
pre-normalizing or assuming availability.

Decision (BACK-3091): ADOPTED — this tool exposes ``amend_outcome`` over
PATCH /v2/api/jobs/{agenticJobId}/outcome, with the platform's optimistic lock
wired up (``expected_entity_version``) rather than as a bare overwrite.

The BACK-2769 decline above is the test, and neither of its two blockers holds
here. (1) Ownership: the Python SDK owns the *in-process* amendment
(``JobContext.amend_outcome``, sdk#108 / sdk#110), where the writer still holds
the handle that reported the outcome. An operator or agent correcting a job
hours later holds no handle, and this tool already writes outcomes for jobs it
did not create — it has no create action either — so the amendment is the same
audience on the same plane as the ``report_outcome`` it already exposes, not a
second implementation of the SDK's path. (2) An input the model cannot observe:
the version token is not one. ``list_jobs`` and ``get_job`` already return
``entityVersion`` (``_strip_links`` removes only ``_links``), so both halves of
the read-then-amend loop live in this tool.

Without the action the tool is a dead end by construction: the outcome POST
answers a second report with 409 "already reported", and the guidance here then
tells the agent to use ``get_job`` to verify. There was no correction path at
all from the MCP for a mis-reported ``outcomeValue``, a ``outcomeReason``
learned later, or a quality fact measured after the job closed.

Safety, read from hypercurrent origin/develop (2026-09-09) rather than assumed:
amendments are append-only in the audit trail — ``JobOutcomeRevisionResource``
rows carry a ``sequence``, so an amendment adds a revision rather than erasing
one; ``UpdateOutcomeRequest.reason`` is nullable for API-key callers, where the
platform records an automated correction reason from the source, so this action
does not force a model to invent a justification (it is still asked for, and
sent when given); and ``expectedEntityVersion`` (``@PositiveOrZero``, "omit for
backward compatibility") makes the lost update detectable. A mismatch is a 409
whose current version exists only in the message prose, which
``_parse_outcome_conflict_version`` lifts into a structured
``RESOURCE_CONFLICT`` error. The lock stays opt-in exactly as in the SDK:
omitted, the platform keeps last-write-wins, the documented backward-compatible
behaviour, and this tool does not silently change it. No automatic retry, at
either layer — the PATCH is not idempotent, so a blind retry appends a
duplicate revision. That is why the 409 is surfaced rather than replayed here,
and why ``ReveniumClient.amend_job_outcome`` passes ``use_retry=False``: the
shared transport otherwise resends on 408, 429 and every 5xx, and a transient
error arriving after the origin committed would append the duplicate this rule
exists to prevent.

Deliberately NOT exposed by this decision: POST .../outcome/metrics, the
append-only fact endpoint (sdk#110). A fact measured later can ride the
``metrics`` array on this same PATCH, and that endpoint's retry semantics
(retryable on 429 only — it has no idempotency key, so a replayed 5xx that the
origin already committed appends a duplicate fact) are a transport concern the
shared MCP client does not model. Revisit when a caller needs to append facts
without touching the outcome row.
"""

import json
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError, raise_unknown_action_error
from ..common.validation import apply_filter_allowlist
from ..introspection.metadata import (
    ResourceRelationship,
    ToolCapability,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


# BACK-1140: client-determinable upper bound on the page parameter.
# Without this, page=2147483647 (32-bit MAX_INT) and similar boundary
# inputs were forwarded straight to the backend, which returned a
# generic HTTP 500 ("An unexpected error occurred, please contact
# Revenium support") instead of a 400 naming the offending field. The
# bound is intentionally generous — even at the smallest documented
# size=1 it covers a million-row job dataset, far beyond what the
# Jobs & Outcomes API surfaces today — so it stays a guard against
# pathological inputs rather than a real cap on legitimate paging.
_MAX_JOBS_PAGE = 1_000_000

# BACK-1140: upper bound on the size parameter. Matches
# PaginationPerformanceManager.MAXIMUM_LIMIT (50), the Revenium API
# absolute maximum. Without this, size=2147483647 (32-bit MAX_INT)
# passed the `size <= 0` guard and was forwarded to the backend, which
# returned the same generic HTTP 500 this PR closed for page.
_MAX_JOBS_SIZE = 50

# snake_case filter name -> camelCase query parameter, bounded to what the
# endpoint declares. Verified 2026-08-28 against hypercurrent origin/develop
# JobController.list, which binds teamId, a Pageable (page, size, sort) and a
# JobSearchParams @ParameterObject whose fields are the names below
# (model/repository/specification/JobSearchParams.kt). teamId and page/size are
# set by the client.
_JOB_FILTER_MAP: Dict[str, str] = {
    "search": "search",
    "type": "type",
    "execution_status": "executionStatus",
    "outcome_type": "outcomeType",
    "outcome_value_min": "outcomeValueMin",
    "outcome_value_max": "outcomeValueMax",
    "environment": "environment",
    "start_date": "startDate",
    "end_date": "endDate",
    "sort": "sort",
}

# BACK-2941: the enum-valued filters, so an unbindable value is refused here
# instead of upstream. The backend answers a value it cannot convert with a
# Spring type-conversion 400 that names its own internal classes, which is
# unreadable and leaks implementation naming. These are the same lists the
# tool publishes through get_capabilities, interpolated from here so the two
# cannot drift. `type` and `environment` are free-form and stay unchecked.
_JOB_EXECUTION_STATUSES: Tuple[str, ...] = ("SUCCESS", "FAILED", "CANCELLED")
_JOB_OUTCOME_TYPES: Tuple[str, ...] = (
    "CONVERTED",
    "ESCALATED",
    "DEFLECTED",
    "UNSUCCESSFUL",
    "CUSTOM",
    "PENDING",
)
_JOB_FILTER_VALUE_ENUMS: Dict[str, Tuple[str, ...]] = {
    "executionStatus": _JOB_EXECUTION_STATUSES,
    "outcomeType": _JOB_OUTCOME_TYPES,
}

# BACK-3091: the outcome POST and the outcome PATCH both accept this array, and
# neither this tool nor ReveniumClient filters it — it simply was not named
# anywhere an agent reads, so an agent that could measure a job's quality had
# nowhere in the guidance telling it where to put the number. Stated once and
# reused by report_outcome and amend_outcome so the two cannot drift.
_OUTCOME_METRICS_NOTE = (
    "metrics (array) — per-job facts the platform evaluates; AI Alerts read "
    "QUALITY_RATE from them. Each entry: key (required, e.g. 'quality_rate'), "
    "value (required), plus optional provenance "
    "(MEASURED|SELF_REPORTED|DERIVED|ATTESTED, server default SELF_REPORTED), "
    "recordedBy, source, reason, recordedAt. recordedBy and source have "
    "server-side defaults (the calling principal, 'api') — filling them in "
    "here would misattribute the fact, so leave them out unless they are "
    "genuinely known. The key must already be declared PER_JOB on the job "
    "type's economics contract; an undeclared key is rejected with a 400 "
    "naming the job type, not silently dropped."
)

# BACK-3091: stated on the read actions and on amend_outcome, because the field
# is already in every job payload and is the only input the amendment's
# optimistic lock takes.
_ENTITY_VERSION_NOTE = (
    "entityVersion — every job read carries it (list_jobs, get_job). It is the "
    "token amend_outcome takes as expected_entity_version: read the job, amend "
    "with the version you read, and a concurrent amendment comes back as a "
    "conflict naming the current version instead of silently overwriting."
)

# BACK-3091: the platform's optimistic-lock conflict on PATCH .../outcome.
# JobService.updateOutcome answers a stale expectedEntityVersion with 409 and
# the message "Outcome has changed since entity version N; current version is
# M" — the version to retry with exists only in that prose, so it is lifted out
# rather than left for a model to parse. A message that does not match is not
# itself an error: the conflict is still reported, without a version, because
# an invented number is worse than an honest "unknown".
_OUTCOME_CONFLICT_VERSION_RE = re.compile(r"current version is\s+(\d+)", re.IGNORECASE)

# BACK-3091: the optimistic-lock token has an argument of its own, but
# outcome_data is a free-form dict forwarded verbatim, so nothing stops a caller
# from putting the platform's own spelling inside it instead. Both spellings are
# lifted out of the body and run through the same coercion as the argument,
# rather than reaching the API unvalidated and coming back as a less useful
# upstream 400. This is the only key this path ever touches, and a valid one goes
# straight back onto the wire body under the platform's spelling, so the verbatim
# forwarding guarantee is intact — nothing is dropped. Lifting it out also fixes
# the emptiness check: a body naming only the lock proposes no change to amend.
_OUTCOME_VERSION_KEYS: Tuple[str, ...] = (
    "expectedEntityVersion",
    "expected_entity_version",
)

# Verified 2026-08-28 against hypercurrent origin/develop
# JobController.getConversionFunnel: @RequestParam teamId / startDate / endDate
# / jobType / environment. teamId is set by the client. The funnel is not
# paginated, so there is no Pageable and no sort.
_CONVERSION_FUNNEL_FILTER_MAP: Dict[str, str] = {
    "start_date": "startDate",
    "end_date": "endDate",
    "job_type": "jobType",
    "environment": "environment",
}

# BACK-2769: the fields a session-attribution interval can carry, in render
# order, paired with the label the rendering uses. The GET's 200 body is a HAL
# CollectionModel whose item schema the platform OpenAPI snapshot leaves
# untyped, so this list follows the operation's own description: a
# management-plane caller — the plane the MCP authenticates on — receives every
# resource field plus the provenance of the write that created the interval
# (``apiKeyId``, ``createdBy``) and of the write that last modified it
# (``modifiedBy``, ``updated``). A METERING-scoped key receives only ticketId,
# ticketTitle and effectiveFrom, with the rest omitted from the response
# entirely rather than nulled. There is no ``splits`` field on this resource;
# see _SESSION_ATTRIBUTION_SPLITS_NOTE.
#
# BACK-3094: the three reason-category fields are on the list because
# ``SessionAttributionIntervalResource`` gained them (PRODUCT-2796) and they
# carry ``Views.SessionAttributionMeteringRead``, so every caller that can read
# an interval at all can read them. Until they were named here the renderer
# withheld their values and counted them on the "additional fields not shown"
# line. Their meanings, one line each, as the resource declares them:
#
# * ``reasonCategory`` — the closed-vocabulary opt-out category recorded for
#   the interval, ``uncategorized`` when nobody was asked, absent on rows
#   written before the vocabulary existed.
# * ``reasonCategoryGroup`` — the activity group the category rolls up into,
#   derived server-side from the registry; absent for the standalone categories
#   (personal, restricted, other, uncategorized), which roll up to no group.
# * ``reasonCategoryWorkClassification`` — the category's derived work
#   classification: WORK, NON_WORK or UNKNOWN (UNKNOWN also covers an
#   unrecognised or absent category).
#
# All three are read-only and derived or closed-vocabulary, so unlike the
# free-text ``reason`` they are not restricted per row — see
# _SESSION_ATTRIBUTION_REASON_NOTE.
_SESSION_ATTRIBUTION_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("ticketId", "Ticket"),
    ("ticketTitle", "Ticket title"),
    ("effectiveFrom", "Effective from"),
    ("source", "Source"),
    ("repo", "Repo"),
    ("branch", "Branch"),
    ("reason", "Reason"),
    ("reasonCategory", "Reason category"),
    ("reasonCategoryGroup", "Reason category group"),
    ("reasonCategoryWorkClassification", "Reason category work classification"),
    ("subscriberEmail", "Subscriber email"),
    ("subscriberEmailSource", "Subscriber email source"),
    ("apiKeyId", "API key id"),
    ("createdBy", "Created by"),
    ("modifiedBy", "Modified by"),
    ("updated", "Updated"),
)

# The list member the CollectionModel wraps intervals in. The snapshot's
# CollectionModel declares exactly one array property, ``objectList``, and that
# is the name to expect; a differently named single list member is accepted
# too, and named in the debug log, so a resource-named list does not turn a
# working read into a failure. Anything else is refused rather than read as
# empty — see _session_attribution_intervals.
_SESSION_ATTRIBUTION_COLLECTION_MEMBER = "objectList"

# Top-level keys a HAL collection may carry alongside (or instead of)
# ``_embedded``. An envelope holding only these, or nothing at all, is an empty
# collection; the platform omits ``_embedded`` entirely when there is nothing to
# embed, and dev answers a session with no attributions with a bare ``{}``
# (verified live 2026-09-04). Any other key set is a shape this code has not
# seen and must not silently render as "no attributions".
_HAL_ENVELOPE_KEYS = frozenset({"_embedded", "_links", "page"})

# Rendered in place of a field the response does not carry, or carries as null.
# Never 0 and never an empty string: an interval with no recorded repo and an
# interval whose repo is genuinely empty must not read the same, and a missing
# value must never render as a real zero.
_SESSION_ATTRIBUTION_UNAVAILABLE = "unavailable"

# BACK-2769: stated on every rendered read, empty collection included. The
# interval resource this GET returns declares no ``splits`` field — splits are
# deliberately not exposed on the read path — so a weighted multi-ticket split
# written through the metering plane reads back here as the interval's single
# scalar ticketId. A single-valued row is not evidence that a split write
# failed, and must not be reported as one.
_SESSION_ATTRIBUTION_SPLITS_NOTE = (
    "Note: this read does not expose splits. The attribution interval "
    "resource returned by GET /v2/api/sessions/{sessionId}/attribution "
    "declares no splits field, so a weighted multi-ticket split written "
    "through another plane reads back here single-valued, as the interval's "
    "scalar ticketId — that is not evidence the split write failed. The MCP "
    "offers no write action for session attribution: the ticket-gate CLI owns "
    "that write on the metering plane (see the Decision (BACK-2769) note at "
    "the top of job_management.py)."
)

# BACK-3094: stated whenever a rendered interval has no ``reason``, because
# from here the three causes are indistinguishable. The platform restricts the
# free-text note twice (PRODUCT-2797): the interval's own subscriber and a
# tenant administrator of the owning tenant are the only management-plane
# callers who receive it, and the owning tenant's attribution-detail-text
# switch withholds it from everyone when it is off. So an ``unavailable``
# Reason must not be read as "no note was written" — the read cannot tell that
# from "not visible to you". ``detailTextSuppressed``, which would separate the
# tenant switch from the visibility check, exists only on the POST resource the
# MCP never receives, so it cannot be reported here. The reason-category fields
# are not restricted this way and stay readable when the note does not.
_SESSION_ATTRIBUTION_REASON_NOTE = (
    "Note: a Reason of "
    f"'{_SESSION_ATTRIBUTION_UNAVAILABLE}' has three possible meanings and "
    "this read cannot tell them apart: no note was recorded for the interval; "
    "a note exists but is not visible to this caller (the platform returns it "
    "only to the subscriber the interval belongs to or to a tenant "
    "administrator of the owning tenant); or the owning tenant's attribution "
    "detail text setting is off, which withholds every note from everyone "
    "(BACK-3096 exposes that setting through the MCP). Do not report it as a "
    "missing note. The reason category fields are not restricted this way, so "
    "they stay readable when the note does not."
)

# The caller-facing filter surface of get_roi_summary. Unchanged from when the
# action aggregated funnels client-side (BACK-2915 swapped the transport, not
# the surface): the action never accepted jobType, because it exists to report
# every job type side by side.
_ROI_SUMMARY_FILTER_MAP: Dict[str, str] = {
    "start_date": "startDate",
    "end_date": "endDate",
    "environment": "environment",
}

# What get_roi_summary actually forwards, and the single statement of why.
# The published operation (isotope GET /api/v2/analytics/jobs/roi-summary)
# declares four query parameters -- startDate, endDate, metricType and jobType.
# This action sends two of them:
#   * jobType is deliberately not accepted from the caller: the action exists to
#     report every job type side by side, and get_conversion_funnel is where a
#     single type is asked for.
#   * metricType is not exposed yet; adding filters is its own change.
# environment is not one of the four at all. The analytics host discards an
# undeclared parameter without an error, so forwarding it would return a
# tenant-wide answer that reads as environment-scoped; it is held back and
# reported to the caller instead of quietly dropped.
_ROI_SUMMARY_FORWARDED_PARAMS: Tuple[str, ...] = ("startDate", "endDate")

# The published byJobType row, field for field. Every row is normalized to this
# set so a field upstream omits reads as _ROI_FIELD_UNAVAILABLE instead of
# defaulting to 0 -- "no external tool cost recorded" and "external tool cost
# of zero" are different answers, and only one of them is safe to divide by.
_ROI_ROW_FIELDS: Tuple[str, ...] = (
    "jobType",
    "totalJobs",
    "totalCost",
    "tokenCost",
    "externalToolCost",
    "humanCost",
    "conversions",
    "deflections",
    "totalValue",
    "averageValue",
    "costPerConversion",
    "costPerOutcome",
    "roi",
    "successRate",
    "toolCostAttribution",
)

# The published summary block, field for field. Normalized the same way.
_ROI_SUMMARY_FIELDS: Tuple[str, ...] = (
    "totalJobTypes",
    "totalJobs",
    "totalCost",
    "totalValue",
    "overallROI",
)

_ROI_FIELD_UNAVAILABLE = "unavailable"

# toolCostAttribution says how externalToolCost reached a job type. Without it
# a reader cannot tell a measured cost from an apportioned one, so the tool
# publishes the qualifier and its meaning rather than folding the number into a
# single total. ALLOCATED_BY_AGENT is the only value the operation declares
# today; an unrecognised one is reported verbatim with no gloss invented for it.
_TOOL_COST_ATTRIBUTION_NOTES: Dict[str, str] = {
    "ALLOCATED_BY_AGENT": (
        "ALLOCATED_BY_AGENT: external tool cost was apportioned to job types "
        "via the agent that incurred it, not measured per job type directly."
    ),
}


def _coerce_expected_entity_version(
    value: Any, source_field: str = "expected_entity_version"
) -> int:
    """Validate the optimistic-lock token supplied to ``amend_outcome``.

    BACK-3091. Rejected here rather than upstream so the caller gets a named
    field instead of a backend 400. ``0`` is a real version (a job that has
    never been amended) and must survive, so nothing about this may be written
    as a truthiness test. ``bool`` is refused explicitly because ``True`` is an
    ``int`` in Python and would silently mean version 1. The two rejected
    shapes — a value of the wrong type and a value that is negative or not a
    whole number — share one refusal on purpose: two copies of the same message
    is how the wording drifts apart on a later edit.

    ``source_field`` names where the value came from, so a version nested in
    ``outcome_data`` is reported against its own key rather than against the
    argument the caller did not use.
    """
    version: Optional[int] = None
    if isinstance(value, int) and not isinstance(value, bool):
        version = value
    elif isinstance(value, str):
        try:
            version = int(value)
        except ValueError:
            version = None
    if version is None or version < 0:
        raise ToolError(
            message=(
                f"{source_field} must be a non-negative integer — the "
                "entityVersion read from get_job or list_jobs"
            ),
            error_code=ErrorCodes.INVALID_PARAMETER,
            field="expected_entity_version",
            value=value,
            suggestions=[
                "Call get_job first and pass the entityVersion it returns",
                "Omit expected_entity_version entirely to amend without the "
                "optimistic lock (last write wins, as the platform's default)",
            ],
        )
    return version


def _parse_outcome_conflict_version(error: ReveniumAPIError) -> Optional[int]:
    """Lift the current entityVersion out of the platform's 409 (BACK-3091).

    The number is only in the message prose, and depending on how the error
    body was decoded it may be on ``message`` or on a string field of
    ``response_data``. Both are searched; ``None`` means the message did not
    match, which is reported as an unknown version rather than guessed at.
    """
    candidates: List[str] = [error.message or ""]
    data = getattr(error, "response_data", None)
    if isinstance(data, dict):
        candidates.extend(value for value in data.values() if isinstance(value, str))
    for text in candidates:
        match = _OUTCOME_CONFLICT_VERSION_RE.search(text)
        if match:
            return int(match.group(1))
    return None


def _strip_links(value: Any) -> Any:
    """Return a copy of ``value`` with all HAL ``_links`` keys removed.

    Upstream HAL+JSON responses embed ``_links.*.href`` URLs that point at
    the internal load-balancer hostname (e.g. ``api-lb.dev.hcapp.io``).
    Forwarding those leaks internal infrastructure topology to MCP callers.
    Strip ``_links`` recursively at the tool boundary so the response carries
    only public-shape fields. Operates on a fresh structure — input is not
    mutated.
    """
    if isinstance(value, dict):
        return {k: _strip_links(v) for k, v in value.items() if k != "_links"}
    if isinstance(value, list):
        return [_strip_links(item) for item in value]
    return value


def _session_attribution_intervals(session_id: str, response: Any) -> List[Any]:
    """Return the interval list from a session-attribution response, or raise.

    ``ReveniumClient._extract_embedded_data`` answers ``[]`` for every shape it
    does not recognise, which on this path would render a malformed or reshaped
    envelope as "no attributions recorded" — a wrong answer that reads like a
    real one. So the shape is checked here instead, and anything unrecognised
    is refused with a structured error naming what came back.

    Accepted, all of them real answers:

    * ``{}`` — what dev returns for a session with no attributions (verified
      live 2026-09-04), and also what the client returns for an empty body.
    * a HAL envelope carrying only ``_links`` / ``page`` and no ``_embedded`` —
      an empty collection, since HAL omits ``_embedded`` when there is nothing
      to embed.
    * a HAL envelope whose ``_embedded`` is a dict with exactly one list-valued
      member, every element of which is an object — the member is ``objectList``
      per the snapshot's ``CollectionModel``, and a single differently named
      list is accepted too (logged, not refused), because a resource-named list
      must not turn a working read into a failure.

    A second list member is refused even when one of them is ``objectList``:
    two lists mean the envelope is not the collection this code knows how to
    read, and picking one would silently drop the other.

    Raises:
        ToolError: for any other shape, carrying the observed top-level keys so
            the caller can see what the platform actually sent.
    """

    def _refuse(detail: str, observed: Any) -> "ToolError":
        return ToolError(
            message=(
                f"Unexpected response shape for the attributions of session "
                f"{session_id}: {detail}. Expected a HAL collection "
                f"(CollectionModel with _embedded."
                f"{_SESSION_ATTRIBUTION_COLLECTION_MEMBER}), or an empty "
                f"envelope when the session has no attributions."
            ),
            error_code=ErrorCodes.API_ERROR,
            context={"session_id": session_id, "observed": observed},
            suggestions=[
                "This is an upstream response-shape change or an error body "
                "reaching this path, not a caller mistake — an empty result is "
                "reported as such and never as an error, so retrying the same "
                "call will not change it",
                "Check GET /v2/api/sessions/{sessionId}/attribution against the "
                "committed snapshot in specs/openapi/hypercurrent.json",
            ],
        )

    if not isinstance(response, dict):
        raise _refuse(
            f"the response is a {type(response).__name__}, not an object",
            type(response).__name__,
        )

    if "_embedded" not in response:
        unknown = sorted(set(response) - _HAL_ENVELOPE_KEYS)
        if unknown:
            raise _refuse(
                "the response carries no _embedded collection and does not look "
                f"like an empty HAL envelope (unrecognised top-level keys: "
                f"{', '.join(unknown)})",
                sorted(response),
            )
        return []

    embedded = response["_embedded"]
    if not isinstance(embedded, dict):
        raise _refuse(
            f"_embedded is a {type(embedded).__name__}, not an object",
            sorted(response),
        )

    lists = {key: value for key, value in embedded.items() if isinstance(value, list)}
    if len(lists) != 1:
        raise _refuse(
            "_embedded holds "
            + (
                "no list member"
                if not lists
                else f"more than one list member ({', '.join(sorted(lists))})"
            ),
            sorted(embedded),
        )

    name, intervals = next(iter(lists.items()))
    if name != _SESSION_ATTRIBUTION_COLLECTION_MEMBER:
        logger.debug(
            f"session attribution collection member is '{name}', not "
            f"'{_SESSION_ATTRIBUTION_COLLECTION_MEMBER}'"
        )

    # Every element must be an object, checked here rather than in the
    # renderer: a non-dict element would otherwise reach the rendering and be
    # printed verbatim, which is both an unreadable row and a way around the
    # field allowlist.
    for index, interval in enumerate(intervals):
        if not isinstance(interval, dict):
            raise _refuse(
                f"element {index} of the '{name}' collection is a "
                f"{type(interval).__name__}, not an attribution object",
                {"member": name, "index": index, "type": type(interval).__name__},
            )
    return intervals


def _render_session_attributions(session_id: str, intervals: List[Any]) -> str:
    """Render one row per attribution interval, newest first.

    Absent fields render as ``unavailable`` rather than as a zero or an empty
    label, because the platform omits fields it will not disclose to the
    caller's plane instead of nulling them.

    Only ``_SESSION_ATTRIBUTION_FIELDS`` are rendered. A field the response
    carries that is not on that list has its NAME reported on a single trailing
    line and its value withheld: growth stays visible, without publishing a
    value nobody has reviewed for sensitivity or shape. Add the field to
    ``_SESSION_ATTRIBUTION_FIELDS`` to start showing it.

    An empty collection is a valid answer, not an error. Every element is an
    object by the time it gets here — ``_session_attribution_intervals`` refuses
    a collection holding anything else, so there is no verbatim fallback that
    could print an unreviewed value.

    BACK-3094: when any rendered interval carries no ``reason``,
    ``_SESSION_ATTRIBUTION_REASON_NOTE`` is stated as well, because an absent
    free-text note has three indistinguishable causes on this path.
    """
    header = f"Session attributions for {session_id}"
    if not intervals:
        return "\n".join(
            [
                header,
                "",
                "No attributions recorded for this session.",
                "",
                _SESSION_ATTRIBUTION_SPLITS_NOTE,
            ]
        )

    known = {name for name, _ in _SESSION_ATTRIBUTION_FIELDS}
    plural = "interval" if len(intervals) == 1 else "intervals"
    lines = [f"{header} ({len(intervals)} {plural}, current first)", ""]
    for index, interval in enumerate(intervals, start=1):
        lines.append(f"{index}.")
        for name, label in _SESSION_ATTRIBUTION_FIELDS:
            value = interval.get(name)
            rendered = _SESSION_ATTRIBUTION_UNAVAILABLE if value is None else value
            lines.append(f"   {label}: {rendered}")
        extras = sorted(key for key in interval if key not in known)
        if extras:
            noun = "field" if len(extras) == 1 else "fields"
            lines.append(
                f"   {len(extras)} additional {noun} not shown: {', '.join(extras)}"
            )
        lines.append("")
    if any(interval.get("reason") is None for interval in intervals):
        lines.append(_SESSION_ATTRIBUTION_REASON_NOTE)
        lines.append("")
    lines.append(_SESSION_ATTRIBUTION_SPLITS_NOTE)
    return "\n".join(lines)


def _normalize_roi_fields(value: Any, fields: Tuple[str, ...]) -> Dict[str, Any]:
    """Return ``value`` projected onto ``fields``, absences marked unavailable.

    Every field the published shape declares appears in the result. A field the
    response omits, or sends as null, becomes ``_ROI_FIELD_UNAVAILABLE`` rather
    than 0: a cost that was never recorded is not a cost of zero, and reporting
    it as one makes an ROI or cost-per-conversion figure look measured when it
    is not. Fields beyond ``fields`` are kept as sent, so a field the API adds
    still reaches the caller without a client release.
    """
    row = value if isinstance(value, dict) else {}
    normalized: Dict[str, Any] = {
        name: row[name] if row.get(name) is not None else _ROI_FIELD_UNAVAILABLE
        for name in fields
    }
    normalized.update({k: v for k, v in row.items() if k not in normalized})
    return normalized


def _require_roi_summary_envelope(response: Any) -> Dict[str, Any]:
    """Return ``response`` once it is the published ROI summary envelope.

    The 200 schema requires id, resourceType, label, period, byJobType, summary
    and _links; the two this tool reads are checked by name and type. Anything
    else raises: a body that is not the published shape is a contract failure,
    and passing it on would render as a successful report of no data -- an
    empty by_job_type list and unavailable totals -- which is exactly what a
    quiet tenant looks like. A genuinely empty window is still the envelope: an
    empty byJobType list alongside a summary block, and it renders as before.

    Raises:
        ToolError: when the response is not a dict, or is missing byJobType as
            a list or summary as an object. The message names what arrived --
            the observed top-level keys, or the type of a non-object body -- so
            the failure can be diagnosed without re-running the call.
    """
    if isinstance(response, dict):
        missing = [
            f"{name} ({expected})"
            for name, expected, ok in (
                ("byJobType", "array", isinstance(response.get("byJobType"), list)),
                ("summary", "object", isinstance(response.get("summary"), dict)),
            )
            if not ok
        ]
        if not missing:
            return response
        observed = f"top-level keys observed: {sorted(response.keys())}"
        detail = f"missing or wrongly typed: {', '.join(missing)}"
    else:
        observed = f"the body is a {type(response).__name__}, not an object"
        detail = "the published response is an object carrying byJobType and summary"

    raise ToolError(
        message=(
            "The job type ROI summary endpoint answered with something other than "
            f"the published envelope; {observed}; {detail}. No summary was returned."
        ),
        error_code=ErrorCodes.API_ERROR,
        suggestions=[
            "Retry the request; a truncated or proxied response can produce this",
            "Verify REVENIUM_APP_BASE_URL points at the analytics host for this environment",
            "If it persists, the endpoint's response contract has changed and the MCP needs updating",
        ],
    )


def _tool_cost_attribution_notes(rows: List[Dict[str, Any]]) -> List[str]:
    """Explain each toolCostAttribution value present in ``rows``.

    A value with no published meaning is still named, so an enum the API grows
    is visible to the caller instead of being filtered out here.
    """
    values = sorted(
        {
            str(row.get("toolCostAttribution"))
            for row in rows
            if row.get("toolCostAttribution") not in (None, _ROI_FIELD_UNAVAILABLE)
        }
    )
    return [
        _TOOL_COST_ATTRIBUTION_NOTES.get(
            value, f"{value}: no published definition for this attribution value."
        )
        for value in values
    ]


def _render_roi_summary(result: Dict[str, Any]) -> str:
    """Render the ROI summary with its qualifiers next to the numbers.

    The figures on their own read as measured and complete. Three things have
    to travel with them: how external tool cost was attributed, which requested
    filters the endpoint could not apply, and that an "unavailable" field is
    missing rather than zero. Putting them above the payload keeps them in
    front of a reader who never expands the JSON.
    """
    lines = ["ROI summary across all job types:"]

    notes = result.get("cost_attribution", {}).get("notes") or []
    if notes:
        lines.append("")
        lines.append("How external tool cost was attributed (toolCostAttribution):")
        lines.extend(f"- {note}" for note in notes)

    not_applied = result.get("filters_not_applied")
    if isinstance(not_applied, dict):
        parameters = ", ".join(not_applied.get("parameters") or [])
        lines.append("")
        lines.append(f"Filters not applied: {parameters}. {not_applied.get('reason', '')}".strip())

    rows = result.get("by_job_type") or []
    scanned = [result.get("summary") or {}, *rows]
    if any(
        _ROI_FIELD_UNAVAILABLE in block.values() for block in scanned if isinstance(block, dict)
    ):
        lines.append("")
        lines.append(
            'Fields shown as "unavailable" were not reported for that job type. '
            "They are missing values, not zeros."
        )

    lines.extend(["", json.dumps(result, indent=2)])
    return "\n".join(lines)


def _validate_jobs_pagination(page: Any, size: Any) -> None:
    """Reject client-determinable boundary inputs with a structured 400.

    Raises:
        ToolError: when page or size is non-integer, negative, or exceeds
            the bound; carries field/value/expected so the caller can fix
            their input without inspecting a server-side traceback.
    """
    for label, value in (("page", page), ("size", size)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolError(
                message=f"{label} must be an integer (got {type(value).__name__})",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field=label,
                value=value,
                suggestions=[
                    f"Pass an integer for {label} (no quotes, no booleans)",
                ],
            )
    if page < 0:
        raise ToolError(
            message=f"page must be >= 0 (got {page})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="page",
            value=page,
            suggestions=["Use page=0 for the first page; pages are zero-indexed"],
        )
    if page > _MAX_JOBS_PAGE:
        raise ToolError(
            message=(
                f"page exceeds maximum (expected 0 <= page <= {_MAX_JOBS_PAGE}, got {page})"
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="page",
            value=page,
            suggestions=[
                "Pick a smaller page; very large indices indicate an off-by-one or "
                "misuse — the underlying dataset never reaches this depth.",
                "If you are looking for a specific job, use get_job(job_id=...) "
                "instead of paginating to find it.",
            ],
        )
    if size <= 0:
        raise ToolError(
            message=f"size must be > 0 (got {size})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="size",
            value=size,
            suggestions=["Use size between 1 and 50 (default 20)"],
        )
    if size > _MAX_JOBS_SIZE:
        raise ToolError(
            message=(
                f"size exceeds maximum (expected 1 <= size <= {_MAX_JOBS_SIZE}, got {size})"
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="size",
            value=size,
            suggestions=[
                f"Use size between 1 and {_MAX_JOBS_SIZE} (default 20)",
                "Paginate with larger page numbers instead of oversized page sizes.",
            ],
        )


class JobManager:
    """Internal manager wrapping async client calls for Jobs & Outcomes API."""

    def __init__(self, client: ReveniumClient):
        self.client = client

    async def list_jobs(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List jobs with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"),
            _JOB_FILTER_MAP,
            action="list_jobs",
            value_enums=_JOB_FILTER_VALUE_ENUMS,
        )
        _validate_jobs_pagination(page, size)
        response = await self.client.get_jobs(page=page, size=size, **filters)
        jobs = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list_jobs",
            "data": _strip_links(jobs),
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": page_info.get("totalPages", 1),
                "total_items": page_info.get("totalElements", len(jobs)),
                "has_next": page < page_info.get("totalPages", 1) - 1,
                "has_previous": page > 0,
            },
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")},
        }

    async def get_job(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a specific job by ID."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for get_job action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        result = await self.client.get_job_by_id(job_id)
        return {"action": "get_job", "job_id": job_id, "data": _strip_links(result)}

    async def get_job_transactions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get transactions for a job."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for get_job_transactions action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        _validate_jobs_pagination(page, size)
        response = await self.client.get_job_transactions(job_id, page=page, size=size)
        transactions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "get_job_transactions",
            "job_id": job_id,
            "data": _strip_links(transactions),
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": page_info.get("totalPages", 1),
                "total_items": page_info.get("totalElements", len(transactions)),
                "has_next": page < page_info.get("totalPages", 1) - 1,
                "has_previous": page > 0,
            },
        }

    async def get_job_roi(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get ROI metrics for a job."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for get_job_roi action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        result = await self.client.get_job_roi(job_id)
        return {"action": "get_job_roi", "job_id": job_id, "data": _strip_links(result)}

    async def get_job_types(self, arguments: Dict[str, Any]) -> Dict[str, Any]:  # noqa: ARG002
        """Get available job types."""
        result = await self.client.get_job_types()
        types = self.client._extract_embedded_data(result) if isinstance(result, dict) else result
        return {"action": "get_job_types", "data": _strip_links(types)}

    async def get_conversion_funnel(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get global conversion funnel analytics with optional filters."""
        # paginated=False: this action takes no page/size arguments, so a
        # page/size inside filters would be a silent no-op rather than a
        # shadowed duplicate - reject it like any other unknown key.
        filters = apply_filter_allowlist(
            arguments.get("filters"),
            _CONVERSION_FUNNEL_FILTER_MAP,
            action="get_conversion_funnel",
            paginated=False,
        )
        result = await self.client.get_job_conversion_funnel(**filters)
        return {"action": "get_conversion_funnel", "data": _strip_links(result)}

    async def get_roi_summary(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get the published ROI summary by job type (BACK-2915).

        One request to the analytics host's job-type ROI summary, which returns
        the per-type cost breakdown (tokenCost, externalToolCost, humanCost),
        the outcome counts, the derived ROI figures, and the
        ``toolCostAttribution`` qualifier saying how external tool cost reached
        each job type. This used to be a get_job_types call plus one
        conversion-funnel request per type, aggregated here; that fan-out could
        not produce the cost breakdown or the qualifier at all, and grew a
        request per job type.

        Filters are bounded by _ROI_SUMMARY_FILTER_MAP; only the parameters the
        operation declares are forwarded, and the rest are reported back as
        not applied.
        """
        filters = apply_filter_allowlist(
            arguments.get("filters"),
            _ROI_SUMMARY_FILTER_MAP,
            action="get_roi_summary",
            paginated=False,
        )
        forwarded = {
            name: value
            for name, value in filters.items()
            if name in _ROI_SUMMARY_FORWARDED_PARAMS
        }
        not_forwarded = sorted(name for name in filters if name not in forwarded)

        try:
            response = await self.client.get_jobs_roi_summary(**forwarded)
        except ReveniumAPIError as exc:
            # A structured error, never an empty summary: a zeroed ROI report is
            # indistinguishable from a real one that happens to be all zeros.
            raise ToolError(
                message=(
                    "The job type ROI summary request failed "
                    f"(status={getattr(exc, 'status_code', 'unknown')}); no summary was returned."
                ),
                error_code=ErrorCodes.API_ERROR,
                suggestions=[
                    "Check API connectivity to the analytics host",
                    "Verify the API key is authorized for /api/v2/analytics/jobs/roi-summary",
                    "Retry with a narrower startDate/endDate window",
                ],
            ) from exc

        payload = _strip_links(_require_roi_summary_envelope(response))
        rows = [
            _normalize_roi_fields(row, _ROI_ROW_FIELDS) for row in payload["byJobType"]
        ]

        result: Dict[str, Any] = {
            "action": "get_roi_summary",
            "summary": _normalize_roi_fields(payload.get("summary"), _ROI_SUMMARY_FIELDS),
            "by_job_type": rows,
            "cost_attribution": {
                "field": "toolCostAttribution",
                "notes": _tool_cost_attribution_notes(rows),
            },
            "period": payload.get("period"),
            "filters_applied": forwarded or None,
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")},
        }
        if not_forwarded:
            # Named, not dropped: the answer is not narrowed by these, and a
            # caller who passed one has to know the result is wider than asked.
            result["filters_not_applied"] = {
                "parameters": not_forwarded,
                "reason": (
                    "The published ROI summary operation does not declare these "
                    "query parameters, so the summary is not narrowed by them."
                ),
            }
        return result

    async def list_session_attributions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List the ticket attributions recorded for a coding-assistant session.

        Read-only. An empty collection means the session has never been
        attributed, which is an answer rather than a failure. Upstream refusals
        (403 for a team the caller cannot read, 404 for an unknown team) are
        left to propagate as ``ReveniumAPIError`` so the standard execution
        path renders them as structured errors carrying the upstream status,
        and a response that is not a collection at all is refused by
        ``_session_attribution_intervals`` rather than rendered as empty.
        """
        session_id = arguments.get("session_id")
        if not session_id:
            raise ToolError(
                message="session_id is required for list_session_attributions action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="session_id",
                examples={
                    "list_session_attributions": {
                        "action": "list_session_attributions",
                        "session_id": "853a73bf-d9d7-4351-a548-9d6c05648c61",
                    }
                },
                suggestions=[
                    "Pass the coding-assistant session identifier — for Claude Code, "
                    "the session UUID",
                    "There is no session listing endpoint: the id comes from the "
                    "assistant that ran the session, not from this tool",
                ],
            )
        response = await self.client.get_session_attributions(session_id)
        intervals = _session_attribution_intervals(session_id, response)
        result: Dict[str, Any] = {
            "action": "list_session_attributions",
            "session_id": session_id,
            "count": len(intervals),
            "data": _strip_links(intervals),
            "splits_note": _SESSION_ATTRIBUTION_SPLITS_NOTE,
        }
        # BACK-3094: carried only when a row actually lacks the free-text note,
        # so a structured consumer is warned exactly when the ambiguity applies.
        if any(interval.get("reason") is None for interval in intervals):
            result["reason_note"] = _SESSION_ATTRIBUTION_REASON_NOTE
        return result

    async def report_outcome(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Report an outcome for a job."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for report_outcome action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        outcome_data = arguments.get("outcome_data")
        if outcome_data is None:
            raise ToolError(
                message="outcome_data is required for report_outcome action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="outcome_data",
                examples={
                    "report_outcome_converted": {
                        "executionStatus": "SUCCESS",
                        "outcomeType": "CONVERTED",
                        "outcomeValue": 99.99,
                        "outcomeCurrency": "USD",
                    },
                    "report_outcome_failed": {
                        "executionStatus": "FAILED",
                        "outcomeType": "UNSUCCESSFUL",
                        "outcomeReason": "Upstream agent timed out after 300s",
                    },
                    "report_outcome_with_metrics": {
                        "executionStatus": "SUCCESS",
                        "outcomeType": "CONVERTED",
                        "outcomeValue": 99.99,
                        "outcomeCurrency": "USD",
                        "metrics": [
                            {
                                "key": "quality_rate",
                                "value": 0.93,
                                "provenance": "MEASURED",
                            }
                        ],
                    },
                },
                suggestions=[
                    "Provide a dict with 'executionStatus' (SUCCESS, FAILED, or CANCELLED) "
                    "plus optional 'outcomeType' (CONVERTED, ESCALATED, DEFLECTED, "
                    "UNSUCCESSFUL, or CUSTOM), 'outcomeValue', and 'outcomeCurrency'",
                    "When executionStatus is FAILED or CANCELLED, explain why in "
                    "'outcomeReason' — a human-readable string; do not bury the reason "
                    "inside 'metadata'",
                    "Keys are camelCase and are sent to the API exactly as given; a "
                    "snake_case or invented key is silently ignored upstream",
                    _OUTCOME_METRICS_NOTE,
                    "The response and every later job read carry " + _ENTITY_VERSION_NOTE,
                ],
            )
        # outcome_data is forwarded verbatim so that fields added to the outcome
        # contract (outcomeReason was the most recent) reach the API without a
        # release here. Do not introduce key filtering or renaming on this path.
        try:
            result = await self.client.report_job_outcome(job_id, outcome_data)
            return {"action": "report_outcome", "job_id": job_id, "data": _strip_links(result)}
        except ReveniumAPIError as e:
            if e.status_code == 409:
                return {
                    "action": "report_outcome",
                    "job_id": job_id,
                    "status": "conflict",
                    "message": (
                        f"Outcome already reported for job {job_id}. "
                        "Duplicate outcomes are not allowed. "
                        "Use amend_outcome to correct it, or get_job to read what "
                        "was recorded."
                    ),
                }
            raise

    async def amend_outcome(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Amend the outcome already reported for a job (BACK-3091).

        See the ``Decision (BACK-3091)`` block in this module's docstring for
        why the MCP owns this write at all. The body is forwarded verbatim for
        the same reason ``report_outcome`` forwards its body verbatim;
        ``expected_entity_version`` is the one argument this action assembles,
        because it is a concurrency token rather than outcome content and a bad
        value is worth rejecting before the request.
        """
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for amend_outcome action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        outcome_data = arguments.get("outcome_data")
        # The lock token is a control field, not outcome content, so it is
        # separated from the body before the body is judged empty: an
        # amendment naming only a version proposes no change at all.
        nested_versions: Dict[str, Any] = {}
        body: Dict[str, Any] = {}
        if isinstance(outcome_data, dict):
            for key, field_value in outcome_data.items():
                if key in _OUTCOME_VERSION_KEYS:
                    nested_versions[key] = field_value
                else:
                    body[key] = field_value
        if not body:
            raise ToolError(
                message=(
                    "outcome_data is required for amend_outcome action and must "
                    "name at least one field to change — an empty amendment "
                    "would burn a revision without changing anything"
                    + (
                        ". A version is the lock, not a change: pass it as the "
                        "expected_entity_version argument and name the field you "
                        "are correcting in outcome_data"
                        if nested_versions
                        else ""
                    )
                ),
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="outcome_data",
                examples={
                    "amend_value": {
                        "reason": "Deal value corrected after invoicing",
                        "outcomeValue": 149.99,
                    },
                    "amend_with_metrics": {
                        "reason": "Quality scored after human review",
                        "metrics": [
                            {
                                "key": "quality_rate",
                                "value": 0.93,
                                "provenance": "MEASURED",
                            }
                        ],
                    },
                },
                suggestions=[
                    "Send only the fields that change: reason, executionStatus, "
                    "outcomeType, outcomeValue, outcomeCurrency, outcomeReason, "
                    "metadata, metrics",
                    "reason is optional for API-key callers — the platform records "
                    "an automated correction reason when it is omitted — but say why "
                    "when you know why, because the revision history is what an "
                    "auditor reads",
                    _OUTCOME_METRICS_NOTE,
                ],
            )
        raw_version = arguments.get("expected_entity_version")
        resolved_version: Optional[int] = None
        if raw_version is not None:
            resolved_version = _coerce_expected_entity_version(raw_version)
        for key, nested_raw in nested_versions.items():
            nested_version = _coerce_expected_entity_version(
                nested_raw, source_field=f"outcome_data.{key}"
            )
            if resolved_version is not None and nested_version != resolved_version:
                raise ToolError(
                    message=(
                        f"Conflicting optimistic-lock versions: outcome_data.{key} "
                        f"says {nested_version} and expected_entity_version says "
                        f"{resolved_version}. Refusing to guess which one you meant "
                        "— amending against the wrong version either overwrites "
                        "another writer or fails for the wrong reason"
                    ),
                    error_code=ErrorCodes.INVALID_PARAMETER,
                    field="expected_entity_version",
                    value=nested_raw,
                    suggestions=[
                        "Pass the version once, as the expected_entity_version "
                        "argument, and keep outcome_data for the fields you are "
                        "changing",
                    ],
                )
            resolved_version = nested_version
        if resolved_version is not None:
            body["expectedEntityVersion"] = resolved_version
        sent_version = body.get("expectedEntityVersion")
        try:
            result = await self.client.amend_job_outcome(job_id, body)
        except ReveniumAPIError as e:
            if e.status_code == 409:
                raise self._outcome_conflict_error(job_id, e, sent_version) from e
            raise
        return {"action": "amend_outcome", "job_id": job_id, "data": _strip_links(result)}

    @staticmethod
    def _outcome_conflict_error(
        job_id: str, error: ReveniumAPIError, sent_version: Any
    ) -> ToolError:
        """Turn the platform's optimistic-lock 409 into a structured conflict.

        Deliberately not retried: the PATCH is not idempotent, so re-sending it
        with the current version would append a duplicate revision on top of
        whatever the other writer just wrote. The caller re-reads, decides
        whether its change still applies, and amends again.
        """
        current_version = _parse_outcome_conflict_version(error)
        current_text = (
            f"current version is {current_version}"
            if current_version is not None
            else "the platform did not name the current version in its response"
        )
        return ToolError(
            message=(
                f"Outcome for job {job_id} changed since entity version "
                f"{sent_version}; {current_text}. The amendment was NOT applied — "
                "another writer amended this outcome first."
            ),
            error_code=ErrorCodes.RESOURCE_CONFLICT,
            field="expected_entity_version",
            value=sent_version,
            context={
                "job_id": job_id,
                "expected_entity_version": sent_version,
                "current_entity_version": current_version,
                "upstream_message": error.message,
            },
            suggestions=[
                f"Call get_job(job_id='{job_id}') to read the amendment that won "
                "and the job's current entityVersion",
                "Decide whether your change still applies on top of it — this is "
                "not retried automatically, because the amendment is not "
                "idempotent and a blind retry appends a duplicate revision",
                "Re-send amend_outcome with expected_entity_version set to the "
                "version you just read",
            ],
        )


class JobManagement(ToolBase):
    """Job management tool for the Jobs & Outcomes system."""

    tool_name = "manage_jobs"
    tool_description = (
        "Job and outcomes management for the Revenium platform. "
        "Track job performance, ROI, conversion funnels, and report outcomes. "
        "Key actions: list_jobs, get_job, get_job_transactions, get_job_roi, "
        "get_job_types, get_conversion_funnel, get_roi_summary, report_outcome, "
        "amend_outcome (correct an outcome already reported), "
        "list_session_attributions (read the ticket a coding session was "
        "attributed to). "
        "Use get_capabilities() for full details or get_examples() for usage templates."
    )
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "1.0.0"

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle job management actions."""
        try:
            client = await self.get_client(ctx=ctx)
            job_manager = JobManager(client)

            # --- Meta-actions ---

            if action == "get_capabilities":
                capabilities = {
                    "tool": self.tool_name,
                    "description": self.tool_description,
                    "version": self.tool_version,
                    "actions": await self._get_supported_actions(),
                    "business_actions": [
                        "list_jobs",
                        "get_job",
                        "get_job_transactions",
                        "get_job_roi",
                        "get_job_types",
                        "get_conversion_funnel",
                        "get_roi_summary",
                        "report_outcome",
                        "amend_outcome",
                        "list_session_attributions",
                    ],
                    "meta_actions": [
                        "get_capabilities",
                        "get_examples",
                        "get_tool_metadata",
                        "get_agent_summary",
                    ],
                    "parameters": {
                        "list_jobs": {
                            "page": "int (default 0)",
                            "size": "int (default 20)",
                            "filters": (
                                "dict (optional) — supported keys: "
                                "search (free text), "
                                "type (job type, case-insensitive), "
                                f"executionStatus ({'|'.join(_JOB_EXECUTION_STATUSES)}), "
                                f"outcomeType ({'|'.join(_JOB_OUTCOME_TYPES)}), "
                                "outcomeValueMin, outcomeValueMax, environment, "
                                "startDate (ISO 8601), endDate (ISO 8601), sort. "
                                "Any other key, and any executionStatus or outcomeType "
                                "value outside the lists above, is rejected here rather "
                                "than sent upstream"
                            ),
                            "returns": (
                                "job records carrying outcomeReason — the human-readable "
                                "explanation of why a job failed or was cancelled (null "
                                "until an outcome with a reason is reported)"
                            ),
                        },
                        "get_job": {
                            "job_id": "str (required)",
                            "returns": (
                                "a job record carrying outcomeReason — read it instead of "
                                "parsing a reason out of outcomeMetadata"
                            ),
                        },
                        "get_job_transactions": {
                            "job_id": "str (required)",
                            "page": "int (default 0)",
                            "size": "int (default 20)",
                        },
                        "get_job_roi": {"job_id": "str (required)"},
                        "get_job_types": {},
                        "get_conversion_funnel": {
                            "filters": (
                                "dict (optional) — supported keys: "
                                "jobType (case-insensitive), startDate (ISO 8601), "
                                "endDate (ISO 8601), environment"
                            ),
                        },
                        "get_roi_summary": {
                            "filters": (
                                "dict (optional) — supported keys: "
                                "startDate (ISO 8601), endDate (ISO 8601), environment. "
                                "The published endpoint declares four query parameters "
                                "(startDate, endDate, metricType, jobType); this action "
                                "forwards startDate and endDate. jobType is not accepted "
                                "because the action reports every job type side by side "
                                "(use get_conversion_funnel for one type), and metricType "
                                "is not exposed yet. environment is not declared by the "
                                "endpoint at all, so it is reported back under "
                                "filters_not_applied instead of narrowing anything."
                            ),
                            "returns": (
                                "One row per job type (by_job_type): totalJobs, totalCost "
                                "split into tokenCost, externalToolCost and humanCost, "
                                "conversions, deflections, totalValue, averageValue, "
                                "costPerConversion, costPerOutcome, roi, successRate, and "
                                "toolCostAttribution. Plus a summary block (totalJobTypes, "
                                "totalJobs, totalCost, totalValue, overallROI). A field the "
                                "endpoint does not report reads as \"unavailable\", never as 0."
                            ),
                            "toolCostAttribution": (
                                "How externalToolCost reached each job type. "
                                "ALLOCATED_BY_AGENT means it was apportioned via the agent "
                                "that incurred the cost, not measured per job type directly "
                                "— read those figures as an allocation, not a measurement."
                            ),
                        },
                        "report_outcome": {
                            "job_id": "str (required)",
                            "outcome_data": (
                                "dict (required), camelCase keys forwarded verbatim: "
                                "executionStatus (SUCCESS|FAILED|CANCELLED, required), "
                                "outcomeType (CONVERTED|ESCALATED|DEFLECTED|UNSUCCESSFUL|CUSTOM), "
                                "outcomeValue (number), outcomeCurrency (ISO 4217, defaults to USD), "
                                "metadata (JSON string), "
                                "outcomeReason (str — human-readable explanation of why the "
                                "job failed or was cancelled). "
                                "outcomeReason is a key of this dict; only job_id and "
                                "outcome_data are read from the call, so a sibling argument "
                                "of any other name is dropped. "
                                + _OUTCOME_METRICS_NOTE
                                + " The response, and every later job read, carry "
                                + _ENTITY_VERSION_NOTE
                            ),
                        },
                        "amend_outcome": {
                            "job_id": "str (required)",
                            "outcome_data": (
                                "dict (required, at least one field), camelCase keys "
                                "forwarded verbatim — the amendment body: reason (str, "
                                "why the correction was made; optional for API-key "
                                "callers, where the platform records an automated "
                                "correction reason instead), plus any of "
                                "executionStatus, outcomeType, outcomeValue, "
                                "outcomeCurrency, outcomeReason, metadata. "
                                + _OUTCOME_METRICS_NOTE
                            ),
                            "expected_entity_version": (
                                "int (optional) — the optimistic lock. Pass the "
                                + _ENTITY_VERSION_NOTE
                                + " Omitted, the platform keeps last-write-wins, so a "
                                "concurrent amendment overwrites yours silently. A "
                                "mismatch is a RESOURCE_CONFLICT error naming the "
                                "current version; it is never retried automatically, "
                                "because the amendment is not idempotent and a retry "
                                "appends a duplicate revision — the transport retry is "
                                "off on this call for the same reason. Passing the "
                                "version inside outcome_data instead works and is "
                                "validated identically, but it must not disagree with "
                                "this argument"
                            ),
                            "history": (
                                "amendments are append-only: each one adds a revision "
                                "with a sequence to the outcome history rather than "
                                "erasing the previous value"
                            ),
                        },
                        "list_session_attributions": {
                            "session_id": (
                                "str (required) — the coding-assistant session "
                                "identifier; for Claude Code, the session UUID. There is "
                                "no session listing endpoint, so this value comes from "
                                "the assistant that ran the session, not from this tool"
                            ),
                            "returns": (
                                "one row per attribution interval, current interval first "
                                "(effectiveFrom descending): "
                                + ", ".join(
                                    name for name, _ in _SESSION_ATTRIBUTION_FIELDS
                                )
                                + ". A field the caller's plane is not shown renders as "
                                f"'{_SESSION_ATTRIBUTION_UNAVAILABLE}', never as 0. An "
                                "empty collection means the session has never been "
                                "attributed and is reported as such, not as an error. "
                                "reasonCategory is the closed-vocabulary opt-out "
                                "category recorded for the interval "
                                "('uncategorized' when nobody was asked), "
                                "reasonCategoryGroup the activity group it rolls up "
                                "into (unavailable for the standalone categories, "
                                "which roll up to no group), and "
                                "reasonCategoryWorkClassification its derived "
                                "classification: WORK, NON_WORK or UNKNOWN"
                            ),
                            "reason": _SESSION_ATTRIBUTION_REASON_NOTE,
                            "splits": _SESSION_ATTRIBUTION_SPLITS_NOTE,
                            "write": (
                                "read-only by decision (BACK-2769): the ticket-gate CLI "
                                "owns the POST on the metering plane, and an MCP model "
                                "has no source for its own session UUID. See the module "
                                "docstring of job_management.py"
                            ),
                        },
                    },
                }
                return [TextContent(type="text", text=json.dumps(capabilities, indent=2))]

            elif action == "get_examples":
                examples = {
                    "list_jobs": {
                        "description": (
                            "List all jobs with pagination. Each job record carries "
                            "outcomeReason, the human-readable explanation of a failed or "
                            "cancelled outcome, and entityVersion, the optimistic-lock "
                            "token amend_outcome takes"
                        ),
                        "example": {"action": "list_jobs", "page": 0, "size": 20},
                        "with_filters": {
                            "action": "list_jobs",
                            "page": 0,
                            "size": 10,
                            "filters": {"type": "loan_processing", "executionStatus": "SUCCESS"},
                        },
                    },
                    "get_job": {
                        "description": (
                            "Get a specific job by ID. The record carries outcomeReason "
                            "alongside outcomeType, outcomeValue and outcomeMetadata, plus "
                            "entityVersion — pass it to amend_outcome as "
                            "expected_entity_version to amend under the optimistic lock"
                        ),
                        "example": {"action": "get_job", "job_id": "job_123"},
                    },
                    "get_job_transactions": {
                        "description": "Get transactions for a job",
                        "example": {
                            "action": "get_job_transactions",
                            "job_id": "job_123",
                            "page": 0,
                            "size": 20,
                        },
                    },
                    "get_job_roi": {
                        "description": "Get ROI metrics for a job",
                        "example": {"action": "get_job_roi", "job_id": "job_123"},
                    },
                    "get_job_types": {
                        "description": "Get all available job types",
                        "example": {"action": "get_job_types"},
                    },
                    "get_conversion_funnel": {
                        "description": "Get global conversion funnel analytics (total/successful/converted)",
                        "example": {"action": "get_conversion_funnel"},
                        "with_filters": {
                            "action": "get_conversion_funnel",
                            "filters": {"startDate": "2025-01-01", "endDate": "2025-12-31", "jobType": "LEAD"},
                        },
                    },
                    "get_roi_summary": {
                        "description": (
                            "Published ROI summary, one row per job type: cost split into "
                            "tokenCost, externalToolCost and humanCost, outcome counts, "
                            "value, roi, successRate, and toolCostAttribution. "
                            "toolCostAttribution=ALLOCATED_BY_AGENT means externalToolCost "
                            "was apportioned to the job type via the agent that incurred "
                            "it rather than measured directly"
                        ),
                        "example": {"action": "get_roi_summary"},
                        "with_filters": {
                            "action": "get_roi_summary",
                            "filters": {"startDate": "2025-01-01", "endDate": "2025-12-31"},
                        },
                    },
                    "report_outcome": {
                        "description": (
                            "Report an outcome for a job (409 = duplicate, already reported). "
                            "outcome_data keys are sent to the API verbatim, so use the "
                            "camelCase spellings below"
                        ),
                        "execution_statuses": list(_JOB_EXECUTION_STATUSES),
                        "outcome_types": [
                            "CONVERTED",
                            "ESCALATED",
                            "DEFLECTED",
                            "UNSUCCESSFUL",
                            "CUSTOM",
                        ],
                        "example_converted": {
                            "action": "report_outcome",
                            "job_id": "job_123",
                            "outcome_data": {
                                "executionStatus": "SUCCESS",
                                "outcomeType": "CONVERTED",
                                "outcomeValue": 99.99,
                                "outcomeCurrency": "USD",
                            },
                        },
                        "example_unsuccessful": {
                            "action": "report_outcome",
                            "job_id": "job_456",
                            "outcome_data": {
                                "executionStatus": "SUCCESS",
                                "outcomeType": "UNSUCCESSFUL",
                                "outcomeReason": "Customer declined after the trial period",
                            },
                        },
                        "example_failed": {
                            "action": "report_outcome",
                            "job_id": "job_789",
                            "outcome_data": {
                                "executionStatus": "FAILED",
                                "outcomeReason": "Upstream agent timed out after 300s",
                            },
                        },
                        "example_with_metrics": {
                            "action": "report_outcome",
                            "job_id": "job_123",
                            "outcome_data": {
                                "executionStatus": "SUCCESS",
                                "outcomeType": "CONVERTED",
                                "outcomeValue": 99.99,
                                "outcomeCurrency": "USD",
                                "metrics": [
                                    {
                                        "key": "quality_rate",
                                        "value": 0.93,
                                        "provenance": "MEASURED",
                                    }
                                ],
                            },
                        },
                        "metrics": _OUTCOME_METRICS_NOTE,
                        "entity_version": _ENTITY_VERSION_NOTE,
                    },
                    "amend_outcome": {
                        "description": (
                            "Correct an outcome that was already reported (the outcome "
                            "POST answers a second report with 409). Send only the "
                            "fields that change; keys are forwarded verbatim. Read the "
                            "job first and pass its entityVersion as "
                            "expected_entity_version so a concurrent amendment is "
                            "reported as a conflict instead of being overwritten"
                        ),
                        "metrics": _OUTCOME_METRICS_NOTE,
                        "entity_version": _ENTITY_VERSION_NOTE,
                        "example_corrected_value": {
                            "action": "amend_outcome",
                            "job_id": "job_123",
                            "expected_entity_version": 2,
                            "outcome_data": {
                                "reason": "Deal value corrected after invoicing",
                                "outcomeValue": 149.99,
                            },
                        },
                        "example_late_quality_metric": {
                            "action": "amend_outcome",
                            "job_id": "job_123",
                            "expected_entity_version": 3,
                            "outcome_data": {
                                "reason": "Quality scored after human review",
                                "metrics": [
                                    {
                                        "key": "quality_rate",
                                        "value": 0.93,
                                        "provenance": "MEASURED",
                                    }
                                ],
                            },
                        },
                        "example_without_the_lock": {
                            "action": "amend_outcome",
                            "job_id": "job_456",
                            "outcome_data": {"outcomeReason": "Customer confirmed churn"},
                        },
                        "conflict": (
                            "409 -> RESOURCE_CONFLICT naming the current entityVersion. "
                            "Re-read with get_job, decide whether your change still "
                            "applies, then amend again with the version you read. Not "
                            "retried automatically: the amendment is not idempotent"
                        ),
                    },
                    "list_session_attributions": {
                        "description": (
                            "Read the ticket attributions recorded for a coding-assistant "
                            "session, current interval first. An empty result means the "
                            "session has never been attributed. This read does not expose "
                            "splits, so a weighted multi-ticket split reads back "
                            "single-valued; the MCP has no write action for session "
                            "attribution (see the Decision (BACK-2769) note in "
                            "job_management.py)"
                        ),
                        "example": {
                            "action": "list_session_attributions",
                            "session_id": "853a73bf-d9d7-4351-a548-9d6c05648c61",
                        },
                    },
                }
                return [TextContent(type="text", text=json.dumps(examples, indent=2))]

            elif action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            elif action == "get_agent_summary":
                summary = await self._get_agent_summary()
                return [TextContent(type="text", text=summary)]

            # --- Business actions ---

            elif action == "list_jobs":
                result = await job_manager.list_jobs(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Jobs (page {arguments.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job":
                result = await job_manager.get_job(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Job details for {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job_transactions":
                result = await job_manager.get_job_transactions(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Transactions for job {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job_roi":
                result = await job_manager.get_job_roi(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"ROI for job {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job_types":
                result = await job_manager.get_job_types(arguments)
                return [
                    TextContent(
                        type="text",
                        text="Available job types:\n\n" + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_conversion_funnel":
                result = await job_manager.get_conversion_funnel(arguments)
                return [
                    TextContent(
                        type="text",
                        text="Conversion funnel analytics:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_roi_summary":
                result = await job_manager.get_roi_summary(arguments)
                return [TextContent(type="text", text=_render_roi_summary(result))]

            elif action == "report_outcome":
                result = await job_manager.report_outcome(arguments)
                if result.get("status") == "conflict":
                    prefix = f"Outcome already exists for job {arguments.get('job_id')}"
                else:
                    prefix = f"Outcome reported for job {arguments.get('job_id')}"
                return [
                    TextContent(
                        type="text",
                        text=f"{prefix}:\n\n" + json.dumps(result, indent=2),
                    )
                ]

            elif action == "amend_outcome":
                result = await job_manager.amend_outcome(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Outcome amended for job {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "list_session_attributions":
                result = await job_manager.list_session_attributions(arguments)
                return [
                    TextContent(
                        type="text",
                        text=_render_session_attributions(
                            result["session_id"], result["data"]
                        ),
                    )
                ]

            else:
                # BACK-2937: raise so the envelope carries the error flag.
                raise_unknown_action_error(action)

        except ReveniumAPIError as e:
            logger.error(f"API error in manage_jobs: {e}")
            raise
        except Exception as e:
            logger.error(f"Error in manage_jobs: {e}")
            raise

    # --- ToolBase metadata method overrides ---

    async def _get_supported_actions(self) -> List[str]:
        """Return all supported actions."""
        return [
            "get_capabilities",
            "get_examples",
            "get_tool_metadata",
            "get_agent_summary",
            "list_jobs",
            "get_job",
            "get_job_transactions",
            "get_job_roi",
            "get_job_types",
            "get_conversion_funnel",
            "get_roi_summary",
            "report_outcome",
            "amend_outcome",
            "list_session_attributions",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get job management tool capabilities."""
        return [
            ToolCapability(
                name="Job Listing and Retrieval",
                description=(
                    "List and retrieve job details with pagination support; job records "
                    "carry outcomeReason for failed or cancelled outcomes"
                ),
                parameters={
                    "list_jobs": {"page": "int", "size": "int", "filters": "dict"},
                    "get_job": {"job_id": "str"},
                },
                examples=["list_jobs(page=0, size=20)", "get_job(job_id='job_123')"],
            ),
            ToolCapability(
                name="Job Analytics",
                description=(
                    "Access job transactions, ROI metrics, conversion funnel data, and "
                    "the published per-job-type ROI summary with its tool-cost "
                    "attribution qualifier"
                ),
                parameters={
                    "get_job_transactions": {"job_id": "str", "page": "int", "size": "int"},
                    "get_job_roi": {"job_id": "str"},
                    "get_conversion_funnel": {"filters": "dict (optional)"},
                    "get_roi_summary": {
                        "filters": "dict (optional: startDate, endDate, environment)",
                        "returns": (
                            "per-job-type cost breakdown (tokenCost, externalToolCost, "
                            "humanCost), outcomes, roi, and toolCostAttribution"
                        ),
                    },
                },
                examples=[
                    "get_job_transactions(job_id='job_123')",
                    "get_job_roi(job_id='job_123')",
                    "get_conversion_funnel(filters={'jobType': 'LEAD'})",
                    "get_roi_summary()",
                    "get_roi_summary(filters={'startDate': '2025-01-01', 'endDate': '2025-12-31'})",
                ],
            ),
            ToolCapability(
                name="Job Types and Outcomes",
                description=(
                    "Retrieve available job types, report a job outcome, and amend "
                    "one already reported. Both outcome bodies accept a metrics "
                    "array of per-job facts (quality_rate and its siblings), and the "
                    "amendment takes the entityVersion carried by every job read as "
                    "an optimistic lock"
                ),
                parameters={
                    "get_job_types": {},
                    "report_outcome": {"job_id": "str", "outcome_data": "dict"},
                    "amend_outcome": {
                        "job_id": "str",
                        "outcome_data": "dict",
                        "expected_entity_version": "int (optional)",
                    },
                },
                examples=[
                    "get_job_types()",
                    "report_outcome(job_id='job_123', outcome_data={'executionStatus': "
                    "'SUCCESS', 'outcomeType': 'CONVERTED', 'outcomeValue': 99.99})",
                    "report_outcome(job_id='job_789', outcome_data={'executionStatus': "
                    "'FAILED', 'outcomeReason': 'Upstream agent timed out after 300s'})",
                    "report_outcome(job_id='job_123', outcome_data={'executionStatus': "
                    "'SUCCESS', 'metrics': [{'key': 'quality_rate', 'value': 0.93, "
                    "'provenance': 'MEASURED'}]})",
                    "amend_outcome(job_id='job_123', expected_entity_version=2, "
                    "outcome_data={'reason': 'Deal value corrected after invoicing', "
                    "'outcomeValue': 149.99})",
                ],
            ),
            ToolCapability(
                name="Coding Session Attribution (read-only)",
                description=(
                    "Read the ticket attributions recorded for a coding-assistant "
                    "session, current interval first. Read-only by decision "
                    "(BACK-2769): the ticket-gate CLI owns the write on the metering "
                    "plane and an MCP model has no source for its own session UUID"
                ),
                parameters={
                    "list_session_attributions": {"session_id": "str (required)"},
                },
                examples=[
                    "list_session_attributions(session_id="
                    "'853a73bf-d9d7-4351-a548-9d6c05648c61')",
                ],
                limitations=[
                    _SESSION_ATTRIBUTION_SPLITS_NOTE,
                    _SESSION_ATTRIBUTION_REASON_NOTE,
                ],
            ),
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships for job management."""
        return [
            ResourceRelationship(
                resource_type="subscriptions",
                relationship_type="enhances",
                description="Jobs track performance outcomes for subscription-based workflows",
                cardinality="N:1",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="customers",
                relationship_type="requires",
                description="Jobs are associated with customer organizations",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="products",
                relationship_type="enhances",
                description="Jobs measure conversion performance against product offerings",
                cardinality="N:M",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get common usage patterns for job management."""
        return [
            UsagePattern(
                pattern_name="Job Performance Review",
                description="Analyze job performance with ROI and transaction data",
                frequency=0.8,
                typical_sequence=["list_jobs", "get_job", "get_job_roi", "get_job_transactions"],
                common_parameters={"page": 0, "size": 20},
                success_indicators=["Jobs listed", "ROI data retrieved"],
            ),
            UsagePattern(
                pattern_name="Conversion Analysis",
                description="Review conversion funnel and report outcomes",
                frequency=0.6,
                typical_sequence=["list_jobs", "get_conversion_funnel", "report_outcome"],
                common_parameters={},
                success_indicators=["Funnel data retrieved", "Outcome reported"],
            ),
            UsagePattern(
                pattern_name="Job Discovery",
                description="Explore available job types and current jobs",
                frequency=0.5,
                typical_sequence=["get_job_types", "list_jobs"],
                common_parameters={},
                success_indicators=["Job types listed", "Jobs enumerated"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent-friendly summary for job management."""
        return """**Job Management Tool (manage_jobs)**

Track and analyze job performance in the Revenium Jobs & Outcomes system.

**Key Actions:**
• list_jobs — List all jobs with pagination
• get_job — Get job details by ID, including outcomeReason for failed or cancelled jobs
• get_job_transactions — View transactions for a job
• get_job_roi — Get ROI metrics for a job
• get_job_types — List available job types
• get_conversion_funnel — View conversion funnel data
• get_roi_summary — Published ROI per job type: tokenCost / externalToolCost / humanCost, outcomes, roi, and toolCostAttribution (ALLOCATED_BY_AGENT = tool cost apportioned via the agent, not measured per job type)
• report_outcome — Report a job outcome (executionStatus plus optional outcomeType,
  outcomeReason, and a metrics array of per-job facts; 409 = already reported)
• amend_outcome — Correct an outcome already reported (reason, any outcome field,
  metrics). Pass expected_entity_version, read from get_job, to be told about a
  concurrent amendment instead of overwriting it
• list_session_attributions — Read the tickets a coding-assistant session was
  attributed to, current first, with the opt-out reason category recorded for
  each interval. Read-only, and the read exposes no splits, so a weighted
  multi-ticket split reads back single-valued. An unavailable Reason can mean
  no note was written, a note not visible to this caller, or the tenant's
  attribution detail text setting being off

**Quick Start:**
1. Call get_capabilities() to explore all parameters
2. Use list_jobs() to find existing jobs
3. Analyze performance with get_job_roi(), get_conversion_funnel(), or get_roi_summary()
4. Report results with report_outcome(), and correct them later with amend_outcome()"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide for job management."""
        return [
            "Call get_capabilities() to see all available actions and parameters",
            "Use list_jobs(page=0, size=20) to browse existing jobs",
            "Get detailed job info with get_job(job_id='...')",
            "Analyze performance using get_job_roi(), get_conversion_funnel(), or get_roi_summary()",
            "Report job outcomes with report_outcome(job_id='...', outcome_data={...})",
            "Correct one with amend_outcome(job_id='...', expected_entity_version=<the "
            "entityVersion from get_job>, outcome_data={...})",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases for job management."""
        return [
            "Track AI job ROI to measure cost-effectiveness of automated workflows",
            "Analyze conversion funnels to identify drop-off points in customer journeys",
            "Report job outcomes to feed data back into the Revenium analytics pipeline",
            "List and filter jobs to monitor active and completed job statuses",
            "Retrieve job transactions for detailed billing and usage audits",
        ]

    async def _get_troubleshooting_tips(self) -> List[str]:
        """Get troubleshooting tips for job management."""
        return [
            "If report_outcome returns a 409 conflict, the outcome was already reported — "
            "read it with get_job and correct it with amend_outcome",
            "If amend_outcome returns RESOURCE_CONFLICT, another writer amended first: "
            "re-read with get_job, decide whether your change still applies, and amend "
            "again with the entityVersion you just read (it is not retried for you — the "
            "amendment is not idempotent)",
            "If list_jobs returns empty results, check filters or try with page=0 and no filters",
            "If get_job_roi returns no data, the job may still be running or not have sufficient transaction history",
            "Ensure job_id is a valid string identifier — use list_jobs to confirm IDs",
            "For pagination, start with page=0 and check has_next to determine if more pages exist",
        ]
