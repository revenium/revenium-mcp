"""Tests for common/thin_tool_defaults.py: what a thin tool's call always carries."""

from src.revenium_mcp_server.common import thin_tool_defaults
from src.revenium_mcp_server.common.thin_tool_defaults import arguments_filled_on_every_call


class TestArgumentsFilledOnEveryCall:
    def test_a_thin_tool_call_carries_the_action_and_the_tools_defaults(self):
        assert arguments_filled_on_every_call("manage_alerts", "list_changes") == {
            "action",
            "page",
            "size",
        }

    def test_a_tool_without_defaults_carries_only_the_action(self):
        assert arguments_filled_on_every_call("manage_metering", "list") == {"action"}

    def test_a_tool_that_is_not_thin_carries_only_the_action(self):
        assert arguments_filled_on_every_call("manage_cost_controls", "list_changes") == {"action"}

    def test_an_actions_own_default_is_carried_by_that_action_alone(self, monkeypatch):
        monkeypatch.setitem(
            thin_tool_defaults.THIN_ACTION_DEFAULTS, "manage_metering", {"list": {"page": 0}}
        )

        assert arguments_filled_on_every_call("manage_metering", "list") == {"action", "page"}
        assert arguments_filled_on_every_call("manage_metering", "get") == {"action"}
