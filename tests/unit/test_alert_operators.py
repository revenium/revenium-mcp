"""Pin the advertised alert operators to the set the platform accepts.

The MCP used to advertise ``EQUAL_TO`` and ``NOT_EQUAL_TO`` for alert creation.
The platform declares both but refuses both on create and update, so an agent that
read the capability output walked into an error the MCP had recommended (BACK-3085).

These tests exist so the next divergence fails here rather than at an agent's create
call: they pin ``revenium_mcp_server.alert_operators`` against the committed OpenAPI
snapshot, and pin every list the MCP advertises against that module.

The snapshot assertions have to survive both shapes the published ``operatorType``
enum has had. The platform now annotates ``AIAnomalyResource.operatorType`` with
exactly the eight accepted operators and keeps it that way
(``EnumSchemaConsistencyTest``), while older snapshots published the wider
``OperatorType`` enum from ``AIAnomaly.kt``, which still carries ``EQUAL_TO`` and
``NOT_EQUAL_TO`` for alerts stored before they were refused. So the mirror asserts
what holds either way: everything advertised is declared, and nothing refused is
advertised — never the size of the gap between the two.
"""

import json
from pathlib import Path
from typing import Any, Dict, Set
from unittest.mock import AsyncMock, MagicMock

import pytest

from revenium_mcp_server.alert_operators import (
    ACCEPTED_OPERATORS,
    CHANGE_OPERATORS,
    COMPARISON_OPERATORS,
    OPERATORS_BY_ALERT_TYPE,
    REJECTED_OPERATORS,
    accepted_operators_for,
    is_rejected_operator,
    rejected_operator_message,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "specs" / "openapi" / "hypercurrent.json"


def _declared_operator_types(snapshot: Path = SNAPSHOT) -> Set[str]:
    """The ``operatorType`` enum as an OpenAPI snapshot declares it.

    The committed snapshot is owned by the nightly drift job and never edited by
    hand, so what it publishes changes under these tests: it has carried both the
    eight accepted operators alone and the wider set including the refused pair.
    The parameter exists so a checkout can be pointed at another snapshot (the
    nightly branch's, say) to confirm these assertions hold for it too.
    """
    if snapshot == SNAPSHOT and not snapshot.exists():
        # Only the committed default is allowed to be absent (the public export
        # keeps specs/openapi/ internal). An explicitly supplied alternate that is
        # missing is a broken test setup and must still fail on read_text().
        pytest.skip(
            "specs/openapi/ is internal-only and not part of the public export "
            "(see public-allowlist-mcp.txt); the snapshot mirror checks run in the internal repo"
        )
    spec = json.loads(snapshot.read_text())
    found: Set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            enum = node.get("enum")
            if isinstance(enum, list) and "GREATER_THAN" in enum and "LESS_THAN" in enum:
                found.update(str(value) for value in enum)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)
    return found


def _operators_section(text: str) -> str:
    """The rendered "Available Operators" section of the capability text."""
    section = text.split("## **Available Operators**", 1)[1]
    return section.split("## **Alert Types**", 1)[0]


def _alert_type_block(section: str, alert_type: str) -> str:
    """The bullets rendered under one alert type heading."""
    block = section.split(f"### **{alert_type}**", 1)[1]
    return block.split("### **", 1)[0]


class TestPlatformMirror:
    """The hand-typed constants against the committed snapshot."""

    def test_snapshot_declares_every_accepted_operator(self):
        declared = _declared_operator_types()
        assert declared, f"no operatorType enum found in {SNAPSHOT}"
        assert set(ACCEPTED_OPERATORS) <= declared, (
            "alert_operators names an operator the platform does not declare: "
            f"{sorted(set(ACCEPTED_OPERATORS) - declared)}"
        )

    def test_no_refused_operator_is_ever_advertised(self):
        """The whole point of the module: refused values are named, never offered.

        This holds whichever enum the snapshot publishes. If the platform starts
        accepting one of the pair, the fix is to move it out of
        ``REJECTED_OPERATORS`` against ``AIAnomalyService.ACCEPTED_OPERATORS`` —
        not to relax this.
        """
        assert not set(REJECTED_OPERATORS) & set(ACCEPTED_OPERATORS)
        for operators in OPERATORS_BY_ALERT_TYPE.values():
            assert not set(REJECTED_OPERATORS) & set(operators)

    def test_a_declared_refused_operator_is_still_not_advertised(self):
        """A snapshot that publishes the wider enum must not widen what we offer.

        The narrowed annotation on ``AIAnomalyResource`` is the platform's current
        shape, but ``OperatorType`` in ``AIAnomaly.kt`` keeps the pair for stored
        alerts, and a snapshot regenerated from that model would publish it again.
        Deriving the advertised list from the snapshot is exactly the mistake
        BACK-3085 was, so assert the derivation never happens.
        """
        for operator in set(REJECTED_OPERATORS) & _declared_operator_types():
            assert operator not in ACCEPTED_OPERATORS
            assert is_rejected_operator(operator)

    def test_accepted_and_rejected_are_disjoint(self):
        assert not set(ACCEPTED_OPERATORS) & set(REJECTED_OPERATORS)

    def test_accepted_is_the_union_of_the_two_families(self):
        assert set(ACCEPTED_OPERATORS) == set(COMPARISON_OPERATORS) | set(CHANGE_OPERATORS)
        assert not set(COMPARISON_OPERATORS) & set(CHANGE_OPERATORS)

    def test_no_duplicate_names(self):
        assert len(ACCEPTED_OPERATORS) == len(set(ACCEPTED_OPERATORS))

    @pytest.mark.parametrize(
        ("alert_type", "expected"),
        [
            ("THRESHOLD", COMPARISON_OPERATORS),
            ("CUMULATIVE_USAGE", COMPARISON_OPERATORS),
            ("RELATIVE_CHANGE", CHANGE_OPERATORS),
        ],
    )
    def test_per_alert_type_sets(self, alert_type, expected):
        """Mirrors AIAnomalyService.acceptedOperatorsFor(alertType) (BACK-3043)."""
        assert accepted_operators_for(alert_type) == expected
        assert OPERATORS_BY_ALERT_TYPE[alert_type] == expected

    def test_every_per_type_operator_is_accepted(self):
        for operators in OPERATORS_BY_ALERT_TYPE.values():
            assert set(operators) <= set(ACCEPTED_OPERATORS)

    def test_unknown_alert_type_falls_back_to_the_full_set(self):
        assert accepted_operators_for("SOMETHING_NEW") == ACCEPTED_OPERATORS

    def test_alert_type_lookup_is_case_insensitive(self):
        assert accepted_operators_for("threshold") == COMPARISON_OPERATORS

    @pytest.mark.parametrize("operator", ["EQUAL_TO", "NOT_EQUAL_TO", "equal_to"])
    def test_is_rejected_operator(self, operator):
        assert is_rejected_operator(operator)

    @pytest.mark.parametrize("operator", ["GREATER_THAN", "INCREASES_BY", ""])
    def test_is_not_rejected_operator(self, operator):
        assert not is_rejected_operator(operator)

    def test_refusal_names_the_alternative_the_platform_names(self):
        message = rejected_operator_message("EQUAL_TO")
        assert "EQUAL_TO" in message
        # AIAnomalyService.operatorNotSupportedMessage points at these four.
        for alternative in COMPARISON_OPERATORS:
            assert alternative in message


class TestAdvertisedLists:
    """Every list the MCP hands an agent, against the platform mirror."""

    @pytest.mark.asyncio
    async def test_capability_discovery_advertises_the_accepted_set(self):
        from revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery

        discovery = CapabilityDiscovery.__new__(CapabilityDiscovery)
        capabilities = await CapabilityDiscovery._discover_alert_capabilities(discovery)

        assert capabilities["operators"] == list(ACCEPTED_OPERATORS)
        assert capabilities["operators_by_alert_type"] == {
            alert_type: list(operators)
            for alert_type, operators in OPERATORS_BY_ALERT_TYPE.items()
        }
        # The refused pair is named as unsupported, not silently dropped, so an
        # agent that already knows the enum learns why it is missing.
        unsupported = capabilities["unsupported_operators"]
        assert unsupported["operators"] == list(REJECTED_OPERATORS)
        for alternative in COMPARISON_OPERATORS:
            assert alternative in unsupported["reason"]

    @pytest.mark.asyncio
    async def test_capability_text_omits_the_refused_pair_and_names_alternatives(self):
        from revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

        tool = AlertManagement.__new__(AlertManagement)
        tool.ucm_helper = None
        text = await tool._build_enhanced_capabilities_text(None)

        operators_section = text.split("## **Available Operators**", 1)[1]
        operators_section = operators_section.split("## **Alert Types**", 1)[0]

        # Named as refused in the guidance, never offered as a choice.
        for alert_type, operators in OPERATORS_BY_ALERT_TYPE.items():
            assert f"### **{alert_type}**" in operators_section
            for operator in operators:
                assert f"- **{operator}**" in operators_section
        for rejected in REJECTED_OPERATORS:
            assert f"- **{rejected}**" not in operators_section
            assert rejected in operators_section
        for alternative in COMPARISON_OPERATORS:
            assert alternative in operators_section

    def test_alert_schema_capabilities_mirror_the_platform(self):
        from revenium_mcp_server.schema.alert_schema import AlertSchemaDiscovery

        capabilities = AlertSchemaDiscovery.__new__(
            AlertSchemaDiscovery
        ).get_capabilities()
        operators = capabilities["operators"]

        assert operators["threshold_operators"] == list(COMPARISON_OPERATORS)
        assert operators["relative_change_operators"] == list(CHANGE_OPERATORS)
        # "all" also carries filter operators, which are a separate vocabulary;
        # what matters is that no refused operatorType appears in it.
        assert set(ACCEPTED_OPERATORS) <= set(operators["all"])
        assert not set(REJECTED_OPERATORS) & set(operators["all"])

    def test_detection_rule_operators_exclude_the_symbolic_exact_match(self):
        """"==" / "!=" are the symbolic spelling of the refused operators."""
        from revenium_mcp_server.exceptions import ValidationError
        from revenium_mcp_server.validators import InputValidator

        for operator in ("==", "!="):
            with pytest.raises(ValidationError) as exc_info:
                InputValidator.validate_detection_rule(
                    {
                        "rule_type": "THRESHOLD",
                        "metric": "total_cost",
                        "operator": operator,
                        "value": 5,
                    }
                )
            assert exc_info.value.details["field"] == "operator"


class TestCreatePathAcceptList:
    """AnomalyManager._validate_direct_api_format is the last gate before the API."""

    @pytest.fixture
    def manager(self):
        from revenium_mcp_server.alerts.anomaly_manager import AnomalyManager

        return AnomalyManager()

    def _payload(self, operator, alert_type="THRESHOLD"):
        return {
            "alertType": alert_type,
            "metricType": "TOTAL_COST",
            "operatorType": operator,
            "threshold": 100,
        }

    @pytest.mark.parametrize("operator", list(COMPARISON_OPERATORS))
    def test_every_comparison_operator_survives_a_threshold_create(
        self, manager, operator
    ):
        """GREATER_THAN_OR_EQUAL_TO used to be refused here: the old accept-list
        spelled it GREATER_THAN_OR_EQUAL, which the platform has no enum constant
        for, so both spellings failed."""
        result = manager._validate_direct_api_format(self._payload(operator))
        assert result["operatorType"] == operator

    @pytest.mark.parametrize("operator", list(CHANGE_OPERATORS))
    def test_every_change_operator_survives_a_relative_change_create(
        self, manager, operator
    ):
        result = manager._validate_direct_api_format(
            self._payload(operator, alert_type="RELATIVE_CHANGE")
        )
        assert result["operatorType"] == operator

    @pytest.mark.parametrize("operator", list(REJECTED_OPERATORS))
    def test_refused_operator_names_the_platform_alternative(self, manager, operator):
        from revenium_mcp_server.exceptions import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            manager._validate_direct_api_format(self._payload(operator))

        error = exc_info.value
        assert error.details["field"] == "operatorType"
        for alternative in COMPARISON_OPERATORS:
            assert alternative in error.message or alternative in str(
                error.details.get("expected", "")
            )

    @pytest.mark.parametrize("operator", ["EQUAL", "NOT_EQUAL", "GREATER_THAN_OR_EQUAL"])
    def test_legacy_operator_spellings_are_refused(self, manager, operator):
        """These are not platform operatorType values. The old accept-list offered
        them, and GREATER_THAN_OR_EQUAL reached the API as an HTTP 400."""
        from revenium_mcp_server.exceptions import ValidationError

        with pytest.raises(ValidationError):
            manager._validate_direct_api_format(self._payload(operator))


class TestReadPathStillAcceptsRefusedOperators:
    """Alerts stored with EQUAL_TO keep rendering — nothing client-side rejects them."""

    @pytest.mark.parametrize(
        ("operator", "symbol"), [("EQUAL_TO", "="), ("NOT_EQUAL_TO", "≠")]
    )
    def test_threshold_summary_renders_a_refused_operator(self, operator, symbol):
        from revenium_mcp_server.alerts.alert_manager import AlertManager

        manager = AlertManager.__new__(AlertManager)
        summary = manager._extract_threshold_condition(
            {"anomaly": {"operatorType": operator, "threshold": 100}}
        )
        assert summary == f"{symbol} 100"

    def test_unknown_operator_passes_through_rather_than_raising(self):
        from revenium_mcp_server.alerts.alert_manager import AlertManager

        manager = AlertManager.__new__(AlertManager)
        summary = manager._extract_threshold_condition(
            {"anomaly": {"operatorType": "SOME_FUTURE_OPERATOR", "threshold": 7}}
        )
        assert "SOME_FUTURE_OPERATOR" in summary


class TestCapabilityTextUsesUcmValues:
    """The rendered per-type sections, driven by UCM rather than the fallback.

    ``test_capability_text_omits_the_refused_pair_and_names_alternatives`` covers
    the fallback. These cover the branch that runs in production, where
    ``CapabilityDiscovery`` has answered and the constants are never reached — a
    wrong key or a broken intersection there would silently render the right text
    from the wrong source.
    """

    def _tool(self):
        from revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

        tool = AlertManagement.__new__(AlertManagement)
        tool.ucm_helper = None
        return tool

    @pytest.mark.asyncio
    async def test_per_type_map_narrows_a_type_below_the_defaults(self):
        """UCM wins over the constants, including when it narrows a type."""
        ucm: Dict[str, Any] = {
            "operators_by_alert_type": {
                "THRESHOLD": ["GREATER_THAN"],
                "CUMULATIVE_USAGE": list(COMPARISON_OPERATORS),
                "RELATIVE_CHANGE": ["PERCENT_INCREASE"],
            }
        }
        section = _operators_section(await self._tool()._build_enhanced_capabilities_text(ucm))

        threshold = _alert_type_block(section, "THRESHOLD")
        assert "- **GREATER_THAN**" in threshold
        # The constants would have offered all four; UCM said one.
        assert "- **LESS_THAN**" not in threshold
        assert "- **GREATER_THAN_OR_EQUAL_TO**" not in threshold

        relative = _alert_type_block(section, "RELATIVE_CHANGE")
        assert "- **PERCENT_INCREASE**" in relative
        assert "- **INCREASES_BY**" not in relative

        # An untouched type still renders in full.
        cumulative = _alert_type_block(section, "CUMULATIVE_USAGE")
        for operator in COMPARISON_OPERATORS:
            assert f"- **{operator}**" in cumulative

    @pytest.mark.asyncio
    async def test_flat_ucm_list_is_split_per_alert_type(self):
        """UCM sending only a flat list must not undo the per-type narrowing."""
        ucm: Dict[str, Any] = {
            "operators": ["GREATER_THAN", "LESS_THAN", "PERCENT_INCREASE"]
        }
        section = _operators_section(await self._tool()._build_enhanced_capabilities_text(ucm))

        threshold = _alert_type_block(section, "THRESHOLD")
        assert "- **GREATER_THAN**" in threshold
        assert "- **LESS_THAN**" in threshold
        # A change operator is never legal on a THRESHOLD alert.
        assert "- **PERCENT_INCREASE**" not in threshold

        relative = _alert_type_block(section, "RELATIVE_CHANGE")
        assert "- **PERCENT_INCREASE**" in relative
        assert "- **GREATER_THAN**" not in relative

    @pytest.mark.asyncio
    async def test_a_refused_operator_from_ucm_is_never_rendered_as_a_choice(self):
        """UCM fed by a platform build that still publishes the declared enum.

        The refused pair has to stay out of the bullets even then — this section
        is what an agent copies its create call from.
        """
        ucm: Dict[str, Any] = {
            "operators_by_alert_type": {
                "THRESHOLD": ["GREATER_THAN", "EQUAL_TO", "NOT_EQUAL_TO"],
            },
            "operators": list(ACCEPTED_OPERATORS) + list(REJECTED_OPERATORS),
        }
        section = _operators_section(await self._tool()._build_enhanced_capabilities_text(ucm))

        for rejected in REJECTED_OPERATORS:
            assert f"- **{rejected}**" not in section
            # Named as refused, so an agent that knows the enum learns why.
            assert rejected in section
        assert "- **GREATER_THAN**" in _alert_type_block(section, "THRESHOLD")

    @pytest.mark.asyncio
    async def test_an_empty_ucm_type_falls_back_to_the_platform_mirror(self):
        ucm: Dict[str, Any] = {"operators_by_alert_type": {"THRESHOLD": []}}
        section = _operators_section(await self._tool()._build_enhanced_capabilities_text(ucm))

        threshold = _alert_type_block(section, "THRESHOLD")
        for operator in COMPARISON_OPERATORS:
            assert f"- **{operator}**" in threshold


class TestUpdatePathAcceptList:
    """Update is a read-modify-write, so it has two operators to answer for.

    The one the caller typed gets the create-path gates. The one the platform
    itself stored does not: refusing that would make an alert created before the
    platform stopped accepting EQUAL_TO impossible to rename, enable or disable
    through the MCP. It is reported instead.
    """

    @pytest.fixture
    def manager(self):
        from revenium_mcp_server.alerts.anomaly_manager import AnomalyManager

        return AnomalyManager()

    def _client(self, stored: Dict[str, Any]) -> MagicMock:
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=stored)
        client.update_anomaly = AsyncMock(return_value={"id": "anom_1", "name": "Alert"})
        return client

    def _stored(self, operator="GREATER_THAN", alert_type="THRESHOLD") -> Dict[str, Any]:
        return {
            "id": "anom_1",
            "name": "Alert",
            "alertType": alert_type,
            "metricType": "TOTAL_COST",
            "operatorType": operator,
            "threshold": 100,
            "enabled": True,
        }

    @pytest.mark.parametrize("operator", list(REJECTED_OPERATORS))
    @pytest.mark.parametrize("field", ["operatorType", "operator_type"])
    @pytest.mark.asyncio
    async def test_update_to_a_refused_operator_never_reaches_the_api(
        self, manager, operator, field
    ):
        """Dev answers this PUT with HTTP 400; the MCP has to answer it first."""
        client = self._client(self._stored())

        result = await manager.update_anomaly(client, "anom_1", {field: operator})

        client.update_anomaly.assert_not_called()
        text = result[0].text
        assert "not supported for AI alerts" in text
        for alternative in COMPARISON_OPERATORS:
            assert alternative in text

    @pytest.mark.asyncio
    async def test_update_to_a_legacy_spelling_never_reaches_the_api(self, manager):
        """GREATER_THAN_OR_EQUAL is not a platform operatorType value."""
        client = self._client(self._stored())

        result = await manager.update_anomaly(
            client, "anom_1", {"operatorType": "GREATER_THAN_OR_EQUAL"}
        )

        client.update_anomaly.assert_not_called()
        assert "Invalid operatorType value" in result[0].text

    @pytest.mark.asyncio
    async def test_update_to_an_operator_the_alert_type_refuses_is_caught(self, manager):
        """acceptedOperatorsFor(RELATIVE_CHANGE) is the change operators only."""
        client = self._client(self._stored(operator="PERCENT_INCREASE", alert_type="RELATIVE_CHANGE"))

        result = await manager.update_anomaly(
            client, "anom_1", {"operatorType": "GREATER_THAN"}
        )

        client.update_anomaly.assert_not_called()
        assert "RELATIVE_CHANGE" in result[0].text

    @pytest.mark.asyncio
    async def test_switching_alert_type_rechecks_the_stored_operator(self, manager):
        """The caller moved the other half of the pairing; same 400 otherwise."""
        client = self._client(self._stored(operator="GREATER_THAN"))

        result = await manager.update_anomaly(
            client, "anom_1", {"alert_type": "RELATIVE_CHANGE"}
        )

        client.update_anomaly.assert_not_called()
        assert "GREATER_THAN" in result[0].text

    @pytest.mark.parametrize("operator", list(ACCEPTED_OPERATORS))
    @pytest.mark.asyncio
    async def test_every_accepted_operator_still_gets_through(self, manager, operator):
        alert_type = "RELATIVE_CHANGE" if operator in CHANGE_OPERATORS else "THRESHOLD"
        client = self._client(self._stored(operator="GREATER_THAN", alert_type=alert_type))

        await manager.update_anomaly(client, "anom_1", {"operatorType": operator})

        assert client.update_anomaly.call_args[0][1]["operatorType"] == operator

    @pytest.mark.parametrize("operator", list(REJECTED_OPERATORS))
    @pytest.mark.asyncio
    async def test_an_unrelated_update_to_a_stored_refused_operator_still_goes_out(
        self, manager, operator
    ):
        """Renaming an alert the platform stored with EQUAL_TO must stay possible."""
        client = self._client(self._stored(operator=operator))

        result = await manager.update_anomaly(client, "anom_1", {"name": "New Name"})

        assert client.update_anomaly.call_args[0][1]["operatorType"] == operator
        text = result[0].text
        assert f"stores operatorType {operator}" in text
        assert "no longer accepts on create or update" in text


class TestEnableDisableWithAStoredRefusedOperator:
    """Enable and disable resubmit the whole stored definition."""

    def _tool(self):
        from revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

        return AlertManagement.__new__(AlertManagement)

    def _client(self, operator: str) -> MagicMock:
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(
            return_value={
                "id": "anom_1",
                "name": "Legacy Alert",
                "alertType": "THRESHOLD",
                "operatorType": operator,
                "threshold": 100,
                "enabled": False,
            }
        )
        client.update_anomaly = AsyncMock(
            return_value={"id": "anom_1", "name": "Legacy Alert"}
        )
        return client

    @pytest.mark.parametrize("operator", list(REJECTED_OPERATORS))
    @pytest.mark.parametrize(
        ("handler", "expected_enabled"),
        [("_handle_enable_anomaly", True), ("_handle_disable_anomaly", False)],
    )
    @pytest.mark.asyncio
    async def test_the_call_goes_out_and_names_the_stored_operator(
        self, operator, handler, expected_enabled
    ):
        client = self._client(operator)

        result = await getattr(self._tool(), handler)(client, {"anomaly_id": "anom_1"})

        sent = client.update_anomaly.call_args[0][1]
        assert sent["enabled"] is expected_enabled
        assert sent["operatorType"] == operator
        assert f"stores operatorType {operator}" in result[0].text

    @pytest.mark.asyncio
    async def test_an_ordinary_alert_gets_no_note(self):
        client = self._client("GREATER_THAN")

        result = await self._tool()._handle_enable_anomaly(client, {"anomaly_id": "anom_1"})

        assert "stores operatorType" not in result[0].text
