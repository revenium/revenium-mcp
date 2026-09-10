"""QUALITY_RATE is offered with its prerequisites, or not offered at all (BACK-3103).

An agent asked to set up a quality alert used to have no way to do it: the metric was
absent from every capability list the MCP publishes, and the substring bucketing behind
those lists would have filed it under performance metrics next to REQUESTS_PER_MINUTE
purely because its name ends in RATE. Offering it naively is worse than not offering it:
the platform evaluates QUALITY_RATE from job outcome facts, so a rule that carries a
groupBy, the wrong alert type, or no TASK_TYPE filter is refused, and a rule on a job
type that never declared the quality_rate metric PER_JOB is accepted and silently never
fires.

These tests pin both halves: what the capability output says, and which payloads the MCP
refuses before they reach the platform. They also pin the thing the fix must *not* do —
introduce a client-side metric enum, which would make every future platform metric an
MCP error.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from revenium_mcp_server.alert_metrics import (
    METRIC_BUCKETS,
    QUALITY_RATE,
    QUALITY_RATE_METRIC_KEY,
    bucket_metrics,
    check_metric_rules,
)
from revenium_mcp_server.exceptions import ValidationError


def _job_type_filter(job_type: str = "code-review") -> Dict[str, Any]:
    return {"dimension": "TASK_TYPE", "operator": "IS", "value": job_type}


def _quality_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Quality floor",
        "alertType": "THRESHOLD",
        "metricType": QUALITY_RATE,
        "operatorType": "LESS_THAN",
        "threshold": 95,
        "filters": [_job_type_filter()],
    }
    payload.update(overrides)
    return payload


class TestMetricBuckets:
    """An explicit mapping decides the bucket, not a substring of the metric name."""

    def test_quality_rate_is_a_quality_metric(self):
        buckets = bucket_metrics(["TOTAL_COST", "REQUESTS_PER_MINUTE", QUALITY_RATE])

        assert QUALITY_RATE in buckets["quality_metrics"]
        assert QUALITY_RATE not in buckets["performance_metrics"]

    def test_error_rate_lands_in_one_bucket_only(self):
        """Substring bucketing put ERROR_RATE in performance *and* quality at once."""
        buckets = bucket_metrics(["ERROR_RATE"])

        assert buckets["quality_metrics"] == ["ERROR_RATE"]
        assert buckets["performance_metrics"] == []

    def test_every_bucket_key_is_always_present(self):
        assert set(bucket_metrics([])) == set(METRIC_BUCKETS)

    def test_an_unknown_metric_still_lands_somewhere(self):
        """A metric the platform adds tomorrow must not vanish from the capability list."""
        buckets = bucket_metrics(["SOME_FUTURE_COST_METRIC"])

        assert buckets["cost_metrics"] == ["SOME_FUTURE_COST_METRIC"]


class TestAdvertisedCapabilities:
    """Every surface that publishes metric groups agrees on where QUALITY_RATE lives."""

    @pytest.mark.asyncio
    async def test_ucm_discovery_buckets_quality_rate_as_quality(self):
        from revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery

        discovery = CapabilityDiscovery(MagicMock())
        capabilities = await discovery.discover_capabilities("alerts")

        metrics = capabilities["metrics"]
        assert QUALITY_RATE in metrics["all"]
        assert QUALITY_RATE in metrics["quality_metrics"]
        assert QUALITY_RATE not in metrics["performance_metrics"]

    @pytest.mark.asyncio
    async def test_ucm_discovery_publishes_the_prerequisites(self):
        from revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery

        discovery = CapabilityDiscovery(MagicMock())
        capabilities = await discovery.discover_capabilities("alerts")

        prerequisites = capabilities["quality_rate"]
        rendered = " ".join(prerequisites["prerequisites"])
        assert QUALITY_RATE_METRIC_KEY in rendered
        assert "PER_JOB" in rendered
        assert "TASK_TYPE" in rendered
        assert "groupBy" in rendered
        assert "minSampleCount" in rendered

    @pytest.mark.asyncio
    async def test_static_metric_capabilities_bucket_quality_rate_as_quality(self):
        from revenium_mcp_server.schema.alert_schema import get_alert_metrics_capabilities

        metrics = await get_alert_metrics_capabilities(None)

        assert QUALITY_RATE in metrics["quality_metrics"]
        assert QUALITY_RATE not in metrics["performance_metrics"]

    @pytest.mark.asyncio
    async def test_capability_text_names_every_prerequisite(self):
        """get_capabilities is what an agent copies from, so the trap has to be in it."""
        from revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

        text = await AlertManagement()._build_enhanced_capabilities_text(None)

        assert QUALITY_RATE in text
        assert QUALITY_RATE_METRIC_KEY in text
        assert "PER_JOB" in text
        assert "TASK_TYPE" in text
        assert "groupBy" in text
        assert "minSampleCount" in text


class TestCreateRejectsBrokenQualityRules:
    """The create path is the last gate before a rule that can never fire is stored."""

    @pytest.fixture
    def manager(self):
        from revenium_mcp_server.alerts.anomaly_manager import AnomalyManager

        return AnomalyManager()

    def test_group_by_is_refused(self, manager):
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(_quality_payload(groupBy="MODEL"))

        error = exc_info.value
        assert error.details["field"] == "groupBy"
        assert "groupBy" in error.message

    @pytest.mark.parametrize("group_by", ["", "   "])
    def test_a_blank_group_by_is_refused_too(self, manager, group_by):
        """An empty groupBy is not an omission: it is forwarded verbatim and the
        platform's GroupBy enum has no member for it, so the call would 400."""
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(_quality_payload(groupBy=group_by))

        error = exc_info.value
        assert error.details["field"] == "groupBy"
        assert QUALITY_RATE in error.message

    def test_an_explicit_null_group_by_is_accepted(self, manager):
        result = manager._validate_direct_api_format(_quality_payload(groupBy=None))

        assert result["metricType"] == QUALITY_RATE

    def test_a_non_threshold_quality_rule_is_refused(self, manager):
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(
                _quality_payload(alertType="CUMULATIVE_USAGE")
            )

        assert exc_info.value.details["field"] == "alertType"

    def test_a_quality_rule_without_a_job_type_filter_is_refused(self, manager):
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(_quality_payload(filters=[]))

        error = exc_info.value
        assert error.details["field"] == "filters"
        assert "TASK_TYPE" in str(error.details.get("expected", "")) + error.message

    def test_a_contains_job_type_filter_is_refused(self, manager):
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(
                _quality_payload(
                    filters=[{"dimension": "TASK_TYPE", "operator": "CONTAINS", "value": "code"}]
                )
            )

        assert exc_info.value.details["field"] == "filters"

    def test_a_complete_quality_rule_is_accepted_and_keeps_its_sample_floor(self, manager):
        result = manager._validate_direct_api_format(_quality_payload(minSampleCount=30))

        assert result["metricType"] == QUALITY_RATE
        assert result["minSampleCount"] == 30
        assert result["filters"] == [_job_type_filter()]

    def test_the_error_names_the_job_type_economics_prerequisite(self, manager):
        """The prerequisite the platform cannot check is the one that silently bites."""
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(_quality_payload(groupBy="MODEL"))

        suggestions = " ".join(exc_info.value.suggestions)
        assert QUALITY_RATE_METRIC_KEY in suggestions
        assert "PER_JOB" in suggestions


class TestMinSampleCountRules:
    """minSampleCount means something on exactly one metric."""

    @pytest.fixture
    def manager(self):
        from revenium_mcp_server.alerts.anomaly_manager import AnomalyManager

        return AnomalyManager()

    def _cost_payload(self, **overrides: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 100,
        }
        payload.update(overrides)
        return payload

    def test_a_sample_floor_on_a_cost_alert_is_refused(self, manager):
        """The platform stores it and never reads it: the caller gets a floor it thinks
        it set and does not have."""
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(self._cost_payload(minSampleCount=30))

        error = exc_info.value
        assert error.details["field"] == "minSampleCount"
        assert QUALITY_RATE in error.message

    @pytest.mark.parametrize("value", [0, -1, 1.5, "30", True])
    def test_a_sample_floor_below_one_or_not_a_count_is_refused(self, manager, value):
        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(_quality_payload(minSampleCount=value))

        assert exc_info.value.details["field"] == "minSampleCount"

    def test_an_explicit_null_sample_floor_is_left_to_the_platform(self, manager):
        """Null is the platform's own "use the safety floor" value, on any metric."""
        result = manager._validate_direct_api_format(self._cost_payload(minSampleCount=None))

        assert result["metricType"] == "TOTAL_COST"


class TestUnknownMetricsStillReachThePlatform:
    """No client-side metric enum: the platform decides what a metric name means."""

    @pytest.fixture
    def manager(self):
        from revenium_mcp_server.alerts.anomaly_manager import AnomalyManager

        return AnomalyManager()

    @pytest.mark.parametrize("metric", [QUALITY_RATE, "SOME_FUTURE_METRIC"])
    def test_a_metric_this_build_does_not_enumerate_is_forwarded(self, manager, metric):
        payload = {
            "alertType": "THRESHOLD",
            "metricType": metric,
            "operatorType": "GREATER_THAN",
            "threshold": 1,
            "filters": [_job_type_filter()],
        }

        result = manager._validate_direct_api_format(payload)

        assert result["metricType"] == metric


class TestUpdateAppliesTheSameRules:
    """An update is a read-modify-write, so the merged body gets the same gates."""

    @pytest.fixture
    def manager(self):
        from revenium_mcp_server.alerts.anomaly_manager import AnomalyManager

        return AnomalyManager()

    def _client(self, stored: Dict[str, Any]) -> MagicMock:
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=stored)
        client.update_anomaly = AsyncMock(return_value={"id": "anom_1", "name": "Quality floor"})
        return client

    def _stored(self) -> Dict[str, Any]:
        return {
            "id": "anom_1",
            "name": "Quality floor",
            "alertType": "THRESHOLD",
            "metricType": QUALITY_RATE,
            "operatorType": "LESS_THAN",
            "threshold": 95,
            "enabled": True,
            "filters": [_job_type_filter()],
        }

    @pytest.mark.asyncio
    async def test_adding_a_group_by_to_a_quality_rule_never_reaches_the_api(self, manager):
        client = self._client(self._stored())

        result = await manager.update_anomaly(client, "anom_1", {"groupBy": "MODEL"})

        client.update_anomaly.assert_not_called()
        assert "groupBy" in result[0].text

    @pytest.mark.asyncio
    async def test_raising_the_sample_floor_reaches_the_api(self, manager):
        client = self._client(self._stored())

        await manager.update_anomaly(client, "anom_1", {"minSampleCount": 50})

        assert client.update_anomaly.call_args[0][1]["minSampleCount"] == 50

    @pytest.mark.asyncio
    async def test_a_sample_floor_on_a_stored_cost_alert_never_reaches_the_api(self, manager):
        stored = self._stored()
        stored["metricType"] = "TOTAL_COST"
        client = self._client(stored)

        result = await manager.update_anomaly(client, "anom_1", {"minSampleCount": 50})

        client.update_anomaly.assert_not_called()
        assert "minSampleCount" in result[0].text


class TestRuleHelperIsTheSingleSource:
    """The helper the paths share, checked directly for the cases they delegate."""

    def test_a_complete_rule_has_no_violation(self):
        assert check_metric_rules(_quality_payload(minSampleCount=5)) is None

    def test_a_cost_alert_without_a_sample_floor_has_no_violation(self):
        assert (
            check_metric_rules(
                {"metricType": "TOTAL_COST", "alertType": "CUMULATIVE_USAGE", "groupBy": "MODEL"}
            )
            is None
        )

    def test_an_unknown_metric_has_no_violation(self):
        assert check_metric_rules({"metricType": "SOME_FUTURE_METRIC", "groupBy": "MODEL"}) is None

    @pytest.mark.parametrize("group_by", ["", "   ", 0])
    def test_a_blank_group_by_is_a_violation_on_any_metric(self, group_by):
        """Nothing else refuses it, and it reaches the wire on every metric."""
        violation = check_metric_rules({"metricType": "TOTAL_COST", "groupBy": group_by})

        assert violation is not None
        assert violation.field == "groupBy"

    def test_a_real_group_by_on_a_cost_alert_is_left_alone(self):
        assert check_metric_rules({"metricType": "TOTAL_COST", "groupBy": "MODEL"}) is None

    def test_a_null_group_by_is_never_a_violation(self):
        assert check_metric_rules(_quality_payload(groupBy=None)) is None

    def test_a_second_filter_alongside_the_job_type_is_a_violation(self):
        payload = _quality_payload(
            filters=[
                _job_type_filter(),
                {"dimension": "MODEL", "operator": "IS", "value": "gpt-4"},
            ]
        )

        violation = check_metric_rules(payload)

        assert violation is not None
        assert violation.field == "filters"


def test_no_client_side_metric_enum_lists_the_platform_metrics() -> None:
    """A regression guard: buckets name what this build knows, they do not gate writes.

    If a future change turns METRIC_BUCKETS into an accept-list, every metric the
    platform adds becomes an MCP error before anyone notices.
    """
    known: List[str] = [metric for metrics in METRIC_BUCKETS.values() for metric in metrics]

    assert "SOME_FUTURE_METRIC" not in known
    assert check_metric_rules({"metricType": "SOME_FUTURE_METRIC"}) is None
