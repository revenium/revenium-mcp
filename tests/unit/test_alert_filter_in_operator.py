"""The IN filter operator and the `values` list it reads (BACK-3102).

An anomaly filter row compares one dimension against one value, except for IN,
which compares against the list in `values` (`AIAnomalyFilter.kt`, BACK-2972).
Getting that pairing wrong is silent upstream - an IN row with no `values`
matches nothing rather than erroring - so the MCP refuses it here, naming the
field the caller left out.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.alert_operators import (
    FILTER_IN_OPERATOR_NOTE,
    FILTER_LIST_OPERATOR,
    FILTER_OPERATORS,
    normalize_filter_operator,
)
from src.revenium_mcp_server.schema.alert_schema import AlertSchemaDiscovery
from src.revenium_mcp_server.schema_discovery import SchemaDiscoveryEngine
from src.revenium_mcp_server.validators import InputValidator
from src.revenium_mcp_server.alerts.anomaly_manager import (
    AnomalyManager,
    format_filter_row,
    validate_filter_rows,
)
from src.revenium_mcp_server.exceptions import ValidationError
from src.revenium_mcp_server.json_schema_validator import JSONSchemaValidator


@pytest.fixture
def manager():
    return AnomalyManager()


class TestFilterOperatorVocabulary:
    """The filter vocabulary is the platform's, and separate from operatorType."""

    def test_in_is_an_accepted_filter_operator(self):
        assert FILTER_LIST_OPERATOR == "IN"
        assert FILTER_LIST_OPERATOR in FILTER_OPERATORS

    def test_matches_the_openapi_snapshot(self):
        """FILTER_OPERATORS mirrors AIAnomalyFilter.operator in the snapshot."""
        snapshot = Path(__file__).resolve().parents[2] / "specs" / "openapi" / "hypercurrent.json"
        if not snapshot.exists():
            pytest.skip(
                "specs/openapi/ is internal-only and not part of the public export "
                "(see public-allowlist-mcp.txt); the snapshot check runs in the internal repo"
            )
        with snapshot.open() as handle:
            spec = json.load(handle)
        published = spec["components"]["schemas"]["AIAnomalyFilter"]["properties"]["operator"][
            "enum"
        ]
        assert set(FILTER_OPERATORS) == set(published)

    def test_aliases_resolve_to_platform_names(self):
        assert normalize_filter_operator("equals") == "IS"
        assert normalize_filter_operator("NOT_EQUALS") == "IS_NOT"
        assert normalize_filter_operator("in") == "IN"

    def test_unknown_operator_is_returned_unchanged(self):
        """The vocabulary never invents a substitute; the caller refuses."""
        assert normalize_filter_operator("matches_regex") == "MATCHES_REGEX"


class TestFilterSchemaDeclaresValues:
    """The published schema has to name `values`, or an agent cannot find it."""

    def _filter_schemas(self):
        schemas = JSONSchemaValidator().schemas["manage_alerts"]["properties"]
        return [
            schemas["anomaly_data"]["properties"]["filters"]["items"],
            schemas["filters"]["items"],
        ]

    def test_both_filter_schemas_declare_values(self):
        for item_schema in self._filter_schemas():
            assert "values" in item_schema["properties"]
            values_schema = item_schema["properties"]["values"]
            assert values_schema["type"] == "array"
            assert values_schema["items"]["type"] == "string"

    def test_both_filter_schemas_accept_in(self):
        for item_schema in self._filter_schemas():
            assert FILTER_LIST_OPERATOR in item_schema["properties"]["operator"]["enum"]

    def test_value_is_no_longer_required(self):
        """An IN row carries no `value`, so requiring it would forbid the shape."""
        for item_schema in self._filter_schemas():
            assert item_schema["required"] == ["dimension", "operator"]

    def test_exclusivity_rule_is_published(self):
        for item_schema in self._filter_schemas():
            assert (
                FILTER_IN_OPERATOR_NOTE in item_schema["properties"]["operator"]["description"]
            )


class TestValidateFilterRows:
    """The row check the create and update paths share."""

    def test_in_row_keeps_its_values_list(self):
        rows = validate_filter_rows(
            [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "claude-sonnet-4-5"]}]
        )
        assert rows == [
            {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "claude-sonnet-4-5"]}
        ]

    def test_in_without_values_is_rejected_naming_values(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows([{"dimension": "MODEL", "operator": "IN", "value": "gpt-4"}])
        assert excinfo.value.details["field"] == "values"
        assert "values" in str(excinfo.value)

    def test_in_with_an_empty_values_list_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows([{"dimension": "MODEL", "operator": "IN", "values": []}])
        assert excinfo.value.details["field"] == "values"

    def test_in_with_a_blank_entry_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows(
                [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "  "]}]
            )
        assert excinfo.value.details["field"] == "values"

    def test_in_ignores_a_scalar_value_the_platform_would_ignore(self):
        rows = validate_filter_rows(
            [{"dimension": "MODEL", "operator": "IN", "value": "", "values": ["gpt-4"]}]
        )
        assert rows == [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4"]}]

    def test_scalar_operator_with_values_and_no_value_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows(
                [{"dimension": "MODEL", "operator": "IS", "values": ["gpt-4", "gpt-5"]}]
            )
        assert excinfo.value.details["field"] == "values"
        assert "IN" in str(excinfo.value)

    def test_scalar_operator_without_value_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows([{"dimension": "MODEL", "operator": "CONTAINS"}])
        assert "value" in str(excinfo.value)

    def test_unknown_operator_is_still_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows(
                [{"dimension": "MODEL", "operator": "MATCHES_REGEX", "value": "gpt.*"}]
            )
        assert excinfo.value.details["field"] == "filters"
        assert "MATCHES_REGEX" in str(excinfo.value)

    def test_aliases_are_mapped(self):
        rows = validate_filter_rows(
            [{"dimension": "PROVIDER", "operator": "equals", "value": "openai"}]
        )
        assert rows == [{"dimension": "PROVIDER", "operator": "IS", "value": "openai"}]

    def test_user_friendly_rows_pass_through_untouched(self):
        """Rows without `dimension` belong to _convert_filters_to_api_format."""
        friendly = [{"field": "provider", "operator": "contains", "value": "openai"}]
        assert validate_filter_rows(friendly) == friendly

    def test_unknown_keys_are_carried_through(self):
        rows = validate_filter_rows(
            [{"dimension": "MODEL", "operator": "IS", "value": "gpt-4", "futureField": 1}]
        )
        assert rows[0]["futureField"] == 1


class TestCreateForwardsTheInRow:
    """The payload the client is handed is what the platform reads."""

    @pytest.mark.asyncio
    async def test_in_row_reaches_the_api_unchanged(self, manager):
        client = MagicMock()
        client.team_id = "team-1"
        client.create_anomaly = AsyncMock(return_value={"id": "anom-1", "name": "Frontier"})

        await manager.create_anomaly(
            client,
            {
                "name": "Frontier",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "operatorType": "GREATER_THAN",
                "threshold": 500,
                "filters": [
                    {
                        "dimension": "MODEL",
                        "operator": "IN",
                        "values": ["gpt-4", "claude-sonnet-4-5"],
                    }
                ],
            },
        )

        sent = client.create_anomaly.call_args[0][0]
        assert sent["filters"] == [
            {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "claude-sonnet-4-5"]}
        ]

    @pytest.mark.asyncio
    async def test_in_without_values_never_reaches_the_api(self, manager):
        client = MagicMock()
        client.team_id = "team-1"
        client.create_anomaly = AsyncMock(return_value={"id": "anom-1"})

        result = await manager.create_anomaly(
            client,
            {
                "name": "Frontier",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "operatorType": "GREATER_THAN",
                "threshold": 500,
                "filters": [{"dimension": "MODEL", "operator": "IN"}],
            },
        )

        client.create_anomaly.assert_not_called()
        assert "values" in result[0].text


class TestUpdateKeepsTheValuesList:
    """The update path rebuilt every row as dimension/operator/value."""

    @pytest.mark.asyncio
    async def test_in_row_survives_an_update(self, manager):
        current = {"id": "anom-1", "name": "Frontier", "enabled": True}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=current)

        await manager.update_anomaly(
            client,
            "anom-1",
            {
                "filters": [
                    {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "gpt-5"]}
                ]
            },
        )

        sent = client.update_anomaly.call_args[0][1]
        assert sent["filters"] == [
            {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "gpt-5"]}
        ]

    @pytest.mark.asyncio
    async def test_in_without_values_is_refused_on_update(self, manager):
        current = {"id": "anom-1", "name": "Frontier", "enabled": True}
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=current)

        result = await manager.update_anomaly(
            client, "anom-1", {"filters": [{"dimension": "MODEL", "operator": "IN"}]}
        )

        client.update_anomaly.assert_not_called()
        assert "values" in result[0].text


class TestRenderingAnInRow:
    """A stored IN row has a null `value`; rendering it showed MODEL IN 'None'."""

    def test_in_row_renders_its_list(self):
        rendered = format_filter_row(
            {"dimension": "MODEL", "operator": "IN", "value": None, "values": ["gpt-4", "gpt-5"]}
        )
        assert rendered == "MODEL IN ['gpt-4', 'gpt-5']"

    def test_scalar_row_still_renders_its_value(self):
        rendered = format_filter_row(
            {"dimension": "PROVIDER", "operator": "IS", "value": "openai"}
        )
        assert rendered == "PROVIDER IS 'openai'"

    def test_in_row_with_no_list_falls_back_to_value(self):
        """A payload this build did not write is rendered, never dropped."""
        rendered = format_filter_row({"dimension": "MODEL", "operator": "IN", "value": "gpt-4"})
        assert rendered == "MODEL IN 'gpt-4'"


class TestValuesEntriesMustBeStrings:
    """Coercion would invent model names the caller never asked for."""

    def test_null_entry_is_rejected_naming_its_index(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows(
                [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", None]}]
            )
        assert excinfo.value.details["field"] == "values"
        assert "index 1" in str(excinfo.value)

    def test_int_entry_is_rejected_rather_than_stringified(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows([{"dimension": "MODEL", "operator": "IN", "values": [42]}])
        assert "index 0" in str(excinfo.value)
        assert "int" in str(excinfo.value)

    def test_nested_list_entry_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows(
                [{"dimension": "MODEL", "operator": "IN", "values": [["gpt-4"]]}]
            )
        assert excinfo.value.details["field"] == "values"

    def test_blank_entry_names_its_index(self):
        with pytest.raises(ValidationError) as excinfo:
            validate_filter_rows(
                [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", " "]}]
            )
        assert "index 1" in str(excinfo.value)


class TestUserFriendlyFilterConversion:
    """The friendly field/operator/value shape lands on the same row check."""

    def test_in_row_converts_to_an_api_row(self):
        rows = InputValidator._convert_filters_to_api_format(
            [{"field": "model", "operator": "in", "values": ["gpt-4", "gpt-5"]}]
        )
        assert rows == [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "gpt-5"]}]

    def test_one_of_is_the_same_operator(self):
        rows = InputValidator._convert_filters_to_api_format(
            [{"field": "provider", "operator": "one_of", "values": ["openai", "anthropic"]}]
        )
        assert rows == [
            {"dimension": "PROVIDER", "operator": "IN", "values": ["openai", "anthropic"]}
        ]

    def test_in_without_values_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            InputValidator._convert_filters_to_api_format(
                [{"field": "model", "operator": "in"}]
            )
        assert excinfo.value.details["field"] == "values"

    def test_in_with_an_empty_list_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            InputValidator._convert_filters_to_api_format(
                [{"field": "model", "operator": "in", "values": []}]
            )
        assert excinfo.value.details["field"] == "values"

    def test_in_with_a_blank_entry_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            InputValidator._convert_filters_to_api_format(
                [{"field": "model", "operator": "in", "values": [""]}]
            )
        assert excinfo.value.details["field"] == "values"

    def test_in_with_only_a_scalar_value_is_rejected(self):
        """Not promoted to a one-entry list: the API-format path refuses the same
        row, and a convenience surface that guessed would teach a shape its
        sibling rejects."""
        with pytest.raises(ValidationError) as excinfo:
            InputValidator._convert_filters_to_api_format(
                [{"field": "model", "operator": "in", "value": "gpt-4"}]
            )
        assert excinfo.value.details["field"] == "values"

    def test_scalar_rows_still_convert(self):
        rows = InputValidator._convert_filters_to_api_format(
            [{"field": "provider", "operator": "contains", "value": "openai"}]
        )
        assert rows == [{"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}]


class TestFilterOperatorsStayOutOfOperatorType:
    """IN is a filter operator; the platform refuses it as an operatorType."""

    def test_alert_schema_operator_lists_exclude_in(self):
        capabilities = AlertSchemaDiscovery().get_capabilities()
        operators = capabilities["operators"]
        for key, published in operators.items():
            assert FILTER_LIST_OPERATOR not in published, key

    def test_alert_schema_publishes_the_filter_vocabulary_separately(self):
        capabilities = AlertSchemaDiscovery().get_capabilities()
        assert capabilities["filter_operators"] == list(FILTER_OPERATORS)
        assert capabilities["filter_row_shape"] == FILTER_IN_OPERATOR_NOTE

    def test_detection_rule_operator_values_exclude_in(self):
        discovery = AlertSchemaDiscovery()
        assert FILTER_LIST_OPERATOR not in discovery._get_valid_values_for_field("operator")

    def test_schema_discovery_engine_matches(self):
        capabilities = SchemaDiscoveryEngine().get_capabilities("anomalies")
        for key, published in capabilities["operators"].items():
            assert FILTER_LIST_OPERATOR not in published, key
        assert capabilities["filter_operators"] == list(FILTER_OPERATORS)


class TestConfirmationsRenderTheList:
    """A create or update confirmation is where the caller checks what was stored."""

    @pytest.mark.asyncio
    async def test_create_confirms_with_the_list(self, manager):
        created = {
            "id": "anom-1",
            "name": "Frontier",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "operatorType": "GREATER_THAN",
            "threshold": 500,
            "filters": [
                {"dimension": "MODEL", "operator": "IN", "value": None, "values": ["gpt-4", "gpt-5"]}
            ],
        }
        client = MagicMock()
        client.team_id = "team-1"
        client.create_anomaly = AsyncMock(return_value=created)

        result = await manager.create_anomaly(
            client,
            {
                "name": "Frontier",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "operatorType": "GREATER_THAN",
                "threshold": 500,
                "filters": [
                    {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "gpt-5"]}
                ],
            },
        )

        assert "MODEL IN ['gpt-4', 'gpt-5']" in result[0].text
        assert "MODEL IN 'None'" not in result[0].text

    @pytest.mark.asyncio
    async def test_update_confirms_with_the_list(self, manager):
        current = {"id": "anom-1", "name": "Frontier", "enabled": True}
        updated = dict(
            current,
            filters=[
                {"dimension": "MODEL", "operator": "IN", "value": None, "values": ["gpt-4", "gpt-5"]}
            ],
        )
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(return_value=current)
        client.update_anomaly = AsyncMock(return_value=updated)

        result = await manager.update_anomaly(
            client,
            "anom-1",
            {"filters": [{"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "gpt-5"]}]},
        )

        assert "MODEL IN ['gpt-4', 'gpt-5']" in result[0].text
