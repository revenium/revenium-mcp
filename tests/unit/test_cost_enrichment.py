"""Unit tests for cost_enrichment helper."""

from src.revenium_mcp_server.analytics.cost_enrichment import enrich_cost_response


class TestTopLevelCurrency:
    def test_empty_dict_gets_currency(self):
        assert enrich_cost_response({}) == {"currency": "USD"}

    def test_existing_dict_gets_currency_added(self):
        result = enrich_cost_response({"foo": "bar"})
        assert result == {"foo": "bar", "currency": "USD"}

    def test_none_returned_unchanged(self):
        assert enrich_cost_response(None) is None

    def test_string_returned_unchanged(self):
        assert enrich_cost_response("not a response") == "not a response"

    def test_existing_currency_preserved(self):
        result = enrich_cost_response({"totalCost": 50, "currency": "EUR"})
        assert result["currency"] == "EUR"


class TestMetricResultFormatting:
    def test_integer_metric_result_formatted(self):
        result = enrich_cost_response({"metricResult": 106344})
        assert result["metricResult"] == 106344
        assert result["metricResult_formatted"] == "$106,344.00"

    def test_float_metric_result_formatted_two_decimals(self):
        result = enrich_cost_response({"metricResult": 480.369})
        assert result["metricResult_formatted"] == "$480.37"

    def test_zero_metric_result_formatted(self):
        result = enrich_cost_response({"metricResult": 0})
        assert result["metricResult_formatted"] == "$0.00"

    def test_small_float_metric_result_formatted(self):
        result = enrich_cost_response({"metricResult": 0.48})
        assert result["metricResult_formatted"] == "$0.48"

    def test_null_metric_result_skipped(self):
        result = enrich_cost_response({"metricResult": None})
        assert "metricResult_formatted" not in result

    def test_string_metric_result_skipped(self):
        result = enrich_cost_response({"metricResult": "106344"})
        assert "metricResult_formatted" not in result

    def test_missing_metric_result_no_formatted_field(self):
        result = enrich_cost_response({"other": 1})
        assert "metricResult_formatted" not in result


class TestTotalCostFormatting:
    def test_integer_total_cost_formatted(self):
        result = enrich_cost_response({"totalCost": 75774})
        assert result["totalCost"] == 75774
        assert result["totalCost_formatted"] == "$75,774.00"

    def test_float_total_cost_formatted(self):
        result = enrich_cost_response({"totalCost": 12.5})
        assert result["totalCost_formatted"] == "$12.50"

    def test_zero_total_cost_formatted(self):
        result = enrich_cost_response({"totalCost": 0})
        assert result["totalCost_formatted"] == "$0.00"

    def test_null_total_cost_skipped(self):
        result = enrich_cost_response({"totalCost": None})
        assert "totalCost_formatted" not in result

    def test_both_cost_fields_in_same_dict(self):
        result = enrich_cost_response({"metricResult": 100, "totalCost": 200})
        assert result["metricResult_formatted"] == "$100.00"
        assert result["totalCost_formatted"] == "$200.00"


class TestNestedWalking:
    def test_nested_dict_metric_result_enriched(self):
        response = {
            "groups": [
                {
                    "groupName": "agent-x",
                    "metrics": [
                        {"metricResult": 106344, "metricType": "COST"}
                    ],
                }
            ]
        }
        result = enrich_cost_response(response)
        metric = result["groups"][0]["metrics"][0]
        assert metric["metricResult"] == 106344
        assert metric["metricResult_formatted"] == "$106,344.00"
        assert metric["metricType"] == "COST"

    def test_list_root_no_top_level_currency(self):
        response = [{"metricResult": 50}]
        result = enrich_cost_response(response)
        assert isinstance(result, list)
        assert "currency" not in result[0]
        # List elements are still walked:
        assert result[0]["metricResult_formatted"] == "$50.00"

    def test_multiple_nested_metrics_all_formatted(self):
        response = {
            "groups": [
                {"metrics": [{"metricResult": 1}, {"metricResult": 2}]},
                {"metrics": [{"metricResult": 3}]},
            ]
        }
        result = enrich_cost_response(response)
        all_metrics = [
            m for g in result["groups"] for m in g["metrics"]
        ]
        assert [m["metricResult_formatted"] for m in all_metrics] == [
            "$1.00", "$2.00", "$3.00"
        ]

    def test_input_not_mutated(self):
        original = {"groups": [{"metrics": [{"metricResult": 100}]}]}
        snapshot = {"groups": [{"metrics": [{"metricResult": 100}]}]}
        enrich_cost_response(original)
        assert original == snapshot
