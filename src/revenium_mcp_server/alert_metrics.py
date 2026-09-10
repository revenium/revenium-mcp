"""How the MCP groups alert metrics, and the prerequisites ``QUALITY_RATE`` carries.

Two separate problems live here.

**Bucketing.** The capability output groups metrics so an agent can find the one it
wants. Every site used to derive those groups by substring — ``"RATE" in metric`` meant
performance, ``"ERROR" in metric`` meant quality — which put ``ERROR_RATE`` in two
buckets at once and would file ``QUALITY_RATE`` under performance, next to
``REQUESTS_PER_MINUTE``, purely because its name ends in ``RATE``. :data:`METRIC_BUCKETS`
is the explicit mapping that decides instead; :func:`bucket_metrics` falls back to the
old substring heuristic only for a metric name this build has never heard of, so a
metric the platform adds tomorrow still appears somewhere rather than vanishing.

**Prerequisites.** ``QUALITY_RATE`` is not a metric an agent can enable the way it
enables a cost alert. The platform evaluates it from job outcome facts, not from AI
transactions, and ``AIAnomalyService.validateQualityRateRule`` (hypercurrent
``origin/develop``, verified 2026-09-09) refuses a rule that does not satisfy all of:

- ``alertType`` is ``THRESHOLD`` — "QUALITY_RATE supports only THRESHOLD alerts".
- ``groupBy`` is null — "QUALITY_RATE alerts do not support groupBy"; the same
  requirement is asserted again in ``AIAlertCriteriaQueryBuilder`` at evaluation time.
- ``minSampleCount``, when present, is at least 1 — "minSampleCount must be at least 1".
- Exactly one filter, a ``TASK_TYPE`` filter with operator ``IS`` and a non-blank job
  type — "QUALITY_RATE alerts require exactly one TASK_TYPE filter with operator IS and
  a job type value". ``AIAlertCriteriaQueryBuilder.getQualityJobType`` reads that filter
  to find the facts.

One prerequisite the platform cannot check at create time: the job type named by that
filter has to declare the ``quality_rate`` metric ``PER_JOB``
(``JobTypeEconomicsService.QUALITY_RATE_METRIC_KEY``) before any quality facts exist. An
alert on a job type without that declaration is accepted, stores fine, and never fires —
the exact failure this module's guidance exists to prevent (BACK-3103).

``minSampleCount`` is read only on the ``QUALITY_RATE`` path. Attached to a cost or token
alert the platform stores it and nothing ever reads it, so the caller believes it set a
coverage floor it did not set. That is why :func:`check_metric_rules` refuses it there
rather than dropping it silently: dropping a field the caller asked for is the same class
of bug as accepting an alert that cannot fire.

One rule here is not about a metric at all: ``groupBy`` is forwarded to the platform
verbatim, and the platform's ``GroupBy`` enum has no empty member, so a present-but-blank
``groupBy`` is refused on any metric rather than treated as an omission.

No client-side metric enum lives here. The buckets name the metrics this build knows
about; a metric outside them still reaches the platform, which is the authority on what
it accepts.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# The metric the platform evaluates from job outcome facts.
QUALITY_RATE: str = "QUALITY_RATE"

# JobTypeEconomicsService.QUALITY_RATE_METRIC_KEY — the per-job metric a job type must
# declare before any quality fact exists for it.
QUALITY_RATE_METRIC_KEY: str = "quality_rate"

# The only alertType AIAnomalyService.validateQualityRateRule accepts for QUALITY_RATE.
QUALITY_RATE_ALERT_TYPE: str = "THRESHOLD"

# The single filter a QUALITY_RATE rule must carry, and the operator it must use.
QUALITY_RATE_FILTER_DIMENSION: str = "TASK_TYPE"

# The MCP lets a caller spell an exact-match filter operator either way and maps it to
# the platform's IS before the call goes out (see AnomalyManager.create_anomaly).
EXACT_MATCH_FILTER_OPERATORS: Tuple[str, ...] = ("IS", "EQUALS", "EQUAL")

# Explicit metric -> bucket mapping. Beats substring matching: ERROR_RATE is a quality
# metric even though its name carries RATE, and QUALITY_RATE is not a performance metric.
METRIC_BUCKETS: Dict[str, Tuple[str, ...]] = {
    "cost_metrics": (
        "TOTAL_COST",
        "COST_PER_TRANSACTION",
    ),
    "token_metrics": (
        "TOKEN_COUNT",
        "INPUT_TOKEN_COUNT",
        "OUTPUT_TOKEN_COUNT",
        "CACHED_TOKEN_COUNT",
    ),
    "performance_metrics": (
        "TOKENS_PER_MINUTE",
        "REQUESTS_PER_MINUTE",
        "TOKENS_PER_SECOND",
        "REQUESTS_PER_SECOND",
    ),
    "quality_metrics": (
        "ERROR_RATE",
        "ERROR_COUNT",
        QUALITY_RATE,
    ),
}

BUCKET_NAMES: Tuple[str, ...] = tuple(METRIC_BUCKETS)

_BUCKET_BY_METRIC: Dict[str, str] = {
    metric: bucket for bucket, metrics in METRIC_BUCKETS.items() for metric in metrics
}

# Ordered fallback for a metric no build knows yet. Quality substrings are tested before
# the rate/throughput ones so a future ERROR_*_RATE lands with the reliability metrics.
_FALLBACK_SUBSTRINGS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("quality_metrics", ("QUALITY", "ERROR")),
    ("cost_metrics", ("COST",)),
    ("token_metrics", ("TOKEN",)),
    ("performance_metrics", ("PER_MINUTE", "PER_SECOND", "RATE", "LATENCY")),
)

# One sentence an agent needs before it reaches for this metric at all.
QUALITY_RATE_SUMMARY: str = (
    "QUALITY_RATE is evaluated from job outcome facts, not from AI transactions, so it "
    "carries prerequisites no other alert metric has. An alert that misses any of them "
    "is either refused on create or stored and never fired."
)

# The prerequisites, in the order an agent has to satisfy them.
QUALITY_RATE_PREREQUISITES: Tuple[str, ...] = (
    f"The job type must declare the `{QUALITY_RATE_METRIC_KEY}` metric PER_JOB in its "
    "job-type economics before any quality facts exist for it (see BACK-3078 / "
    "BACK-3090). Without that declaration there are no facts to evaluate and the alert "
    "never fires, whatever the threshold says. The platform answers a create on an "
    "undeclared job type with `HTTP 400 ... QUALITY_RATE job type '<name>' is not "
    "registered for this organization`.",
    f"Exactly one filter: dimension `{QUALITY_RATE_FILTER_DIMENSION}`, operator `IS`, "
    "value the job type name. That filter is how the evaluation finds the facts, so a "
    "second filter, a different operator, or no filter at all is refused.",
    f"`alertType` must be `{QUALITY_RATE_ALERT_TYPE}` — cumulative-usage and "
    "relative-change quality rules are not supported.",
    "No `groupBy`. A quality rule is evaluated over the job type as a whole.",
    "`minSampleCount` (optional, integer >= 1) is how many quality facts the period "
    "must contain before the rule can fire; below that floor the evaluation reports "
    "insufficient coverage instead of alerting. It is read on the QUALITY_RATE path "
    "only — on any other metric it is stored and never consulted, so the MCP refuses "
    "it there.",
)


def bucket_metrics(metrics: Iterable[str]) -> Dict[str, List[str]]:
    """Group ``metrics`` into the advertised buckets, explicit mapping first.

    Every bucket in :data:`METRIC_BUCKETS` is present in the result even when empty, so
    a caller rendering the buckets does not have to guard each key. Input order is
    preserved inside a bucket, and a metric lands in exactly one bucket.
    """
    grouped: Dict[str, List[str]] = {bucket: [] for bucket in METRIC_BUCKETS}
    for metric in metrics:
        bucket = bucket_for_metric(metric)
        if bucket is not None:
            grouped[bucket].append(metric)
    return grouped


def bucket_for_metric(metric: str) -> Optional[str]:
    """The bucket ``metric`` belongs to, or ``None`` when nothing claims it."""
    name = str(metric).upper()
    explicit = _BUCKET_BY_METRIC.get(name)
    if explicit is not None:
        return explicit
    for bucket, substrings in _FALLBACK_SUBSTRINGS:
        if any(substring in name for substring in substrings):
            return bucket
    return None


@dataclass(frozen=True)
class MetricRuleViolation:
    """A metric prerequisite the submitted alert breaks, phrased for the caller."""

    field: str
    message: str
    expected: str
    suggestion: str
    value: Any = None


def is_quality_rate(metric_type: Any) -> bool:
    """Whether ``metric_type`` names the quality metric."""
    return isinstance(metric_type, str) and metric_type.strip().upper() == QUALITY_RATE


def _quality_rate_suggestion() -> str:
    return "QUALITY_RATE prerequisites: " + " ".join(QUALITY_RATE_PREREQUISITES)


def _task_type_filters(filters: Any) -> List[Mapping[str, Any]]:
    if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
        return []
    matches: List[Mapping[str, Any]] = []
    for entry in filters:
        if not isinstance(entry, Mapping):
            continue
        dimension = str(entry.get("dimension", "")).strip().upper()
        if dimension == QUALITY_RATE_FILTER_DIMENSION:
            matches.append(entry)
    return matches


def _check_min_sample_count(payload: Mapping[str, Any]) -> Optional[MetricRuleViolation]:
    if "minSampleCount" not in payload:
        return None

    value = payload["minSampleCount"]
    if value is None:
        # Explicitly null is what the platform reads as "use the safety floor".
        return None

    metric_type = payload.get("metricType")
    if not is_quality_rate(metric_type):
        return MetricRuleViolation(
            field="minSampleCount",
            value=value,
            message=(
                f"minSampleCount applies to {QUALITY_RATE} alerts only, and this alert "
                f"is on {metric_type or 'no metric'}"
            ),
            expected=f"minSampleCount only alongside metricType {QUALITY_RATE}",
            suggestion=(
                "The platform reads minSampleCount on the QUALITY_RATE path only. On "
                "any other metric it is stored and never consulted, so the alert would "
                "have no coverage floor even though the call looked like it set one. "
                "Drop minSampleCount, or switch the alert to QUALITY_RATE. "
                + _quality_rate_suggestion()
            ),
        )

    # bool is an int in Python; True as a sample floor is a mistake, not a count.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return MetricRuleViolation(
            field="minSampleCount",
            value=value,
            message="minSampleCount must be a whole number of quality facts, at least 1",
            expected="Integer >= 1",
            suggestion=(
                "minSampleCount is how many quality facts the period must contain "
                "before the rule can fire (the platform refuses anything below 1). "
                "Omit it to accept the platform's one-sample safety floor."
            ),
        )
    return None


def check_metric_rules(payload: Mapping[str, Any]) -> Optional[MetricRuleViolation]:
    """The first metric prerequisite ``payload`` breaks, or ``None`` when it breaks none.

    ``payload`` is an alert body in API shape (``metricType``, ``alertType``, ``groupBy``,
    ``filters``, ``minSampleCount``). Every rule mirrors
    ``AIAnomalyService.validateQualityRateRule``, so a rejection here is one the platform
    would have issued anyway — just earlier, and with the prerequisite spelled out.

    Nothing here validates the metric name itself: an unrecognised metric passes straight
    through to the platform.
    """
    violation = _check_min_sample_count(payload)
    if violation is not None:
        return violation

    quality_rule = is_quality_rate(payload.get("metricType"))

    # ``groupBy`` is forwarded to the platform verbatim, so a value that is present but
    # unusable has to be answered here. Only ``None`` counts as "not grouping": the
    # platform's GroupBy enum has no empty member, so "" and "   " are an HTTP 400
    # waiting to happen rather than an omission. Refusing rather than quietly
    # normalising them to null matches how this validator already answers an invalid
    # periodDuration or a non-boolean enabled, and staying silent would repeat the
    # class of bug this module exists to close: a caller told nothing while the alert
    # it asked for is not the alert it gets.
    group_by = payload.get("groupBy")
    if group_by is not None:
        if quality_rule:
            return MetricRuleViolation(
                field="groupBy",
                value=group_by,
                message=f"{QUALITY_RATE} alerts do not support groupBy",
                expected="groupBy omitted, or null (the platform requires it to be null)",
                suggestion=(
                    "A quality rule is evaluated over one job type as a whole, named by "
                    f"its {QUALITY_RATE_FILTER_DIMENSION} filter, so there is nothing to "
                    "group by. Remove groupBy — an empty string is not an omission, it "
                    "is a value the platform's GroupBy enum has no member for — or "
                    "create one alert per job type. " + _quality_rate_suggestion()
                ),
            )
        if not isinstance(group_by, str) or not group_by.strip():
            return MetricRuleViolation(
                field="groupBy",
                value=group_by,
                message="groupBy must name a grouping dimension when it is present",
                expected="A grouping dimension name, or groupBy omitted entirely (null)",
                suggestion=(
                    "An empty or blank groupBy is not the same as no groupBy: it is "
                    "forwarded as-is and the platform's GroupBy enum has no member for "
                    "it, so the call comes back HTTP 400. Omit the field to leave the "
                    "alert ungrouped."
                ),
            )

    if not quality_rule:
        return None

    alert_type = payload.get("alertType")
    if alert_type is not None and str(alert_type).strip().upper() != QUALITY_RATE_ALERT_TYPE:
        return MetricRuleViolation(
            field="alertType",
            value=alert_type,
            message=f"{QUALITY_RATE} supports only {QUALITY_RATE_ALERT_TYPE} alerts",
            expected=f"alertType {QUALITY_RATE_ALERT_TYPE}",
            suggestion=(
                "A quality rate is a rate, not a running total or a period-over-period "
                f"change, so the platform evaluates it as a {QUALITY_RATE_ALERT_TYPE} "
                "rule only. " + _quality_rate_suggestion()
            ),
        )

    filters = payload.get("filters") or []
    job_type_filters = _task_type_filters(filters)
    if len(job_type_filters) != 1 or len(list(filters)) != 1:
        return MetricRuleViolation(
            field="filters",
            value=filters,
            message=(
                f"{QUALITY_RATE} alerts require exactly one "
                f"{QUALITY_RATE_FILTER_DIMENSION} filter naming the job type"
            ),
            expected=(
                f'filters: [{{"dimension": "{QUALITY_RATE_FILTER_DIMENSION}", '
                '"operator": "IS", "value": "<job type>"}]'
            ),
            suggestion=(
                "That filter is how the evaluation finds the job outcome facts to "
                "average, so it is the alert's subject rather than a narrowing. "
                + _quality_rate_suggestion()
            ),
        )

    job_type_filter = job_type_filters[0]
    operator = str(job_type_filter.get("operator", "")).strip().upper()
    if operator not in EXACT_MATCH_FILTER_OPERATORS:
        return MetricRuleViolation(
            field="filters",
            value=job_type_filter.get("operator"),
            message=(
                f"The {QUALITY_RATE_FILTER_DIMENSION} filter on a {QUALITY_RATE} alert "
                "must match the job type exactly"
            ),
            expected="operator IS",
            suggestion=(
                "A CONTAINS or IS_NOT job-type filter cannot resolve to the single job "
                "type whose quality facts the rule averages. " + _quality_rate_suggestion()
            ),
        )

    job_type = job_type_filter.get("value")
    if not isinstance(job_type, str) or not job_type.strip():
        return MetricRuleViolation(
            field="filters",
            value=job_type,
            message=(
                f"The {QUALITY_RATE_FILTER_DIMENSION} filter on a {QUALITY_RATE} alert "
                "needs the job type name as its value"
            ),
            expected="A non-empty job type name",
            suggestion=(
                f"The job type must already declare the {QUALITY_RATE_METRIC_KEY} metric "
                "PER_JOB, otherwise no quality facts exist for it and the alert never "
                "fires. " + _quality_rate_suggestion()
            ),
        )

    return None
