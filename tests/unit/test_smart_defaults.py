"""Unit tests for SmartDefaultsEngine: alert/customer/source defaults and merging."""

import pytest

from src.revenium_mcp_server.smart_defaults import SmartDefaultsEngine


class TestSmartDefaultsEngine:
    """Test SmartDefaultsEngine default value generation and merging."""

    def setup_method(self):
        self.engine = SmartDefaultsEngine()

    # -----------------------------------------------------------------------
    # Alert defaults
    # -----------------------------------------------------------------------

    def test_alert_defaults_threshold(self):
        defaults = self.engine.get_alert_defaults("threshold")
        assert defaults["alertType"] == "THRESHOLD"
        assert defaults["enabled"] is True
        assert defaults["detection_rules"][0]["rule_type"] == "THRESHOLD"

    def test_alert_defaults_cumulative_usage(self):
        defaults = self.engine.get_alert_defaults("cumulative_usage")
        assert defaults["alertType"] == "CUMULATIVE_USAGE"
        assert defaults["period"] == "monthly"

    def test_alert_defaults_budget_alias(self):
        """'budget' is an alias for cumulative_usage."""
        defaults = self.engine.get_alert_defaults("budget")
        assert defaults["alertType"] == "CUMULATIVE_USAGE"

    def test_alert_defaults_relative_change(self):
        defaults = self.engine.get_alert_defaults("relative_change")
        assert defaults["alertType"] == "RELATIVE_CHANGE"
        assert defaults["detection_rules"][0]["is_percentage"] is True

    def test_alert_defaults_unknown_returns_base(self):
        defaults = self.engine.get_alert_defaults("something_else")
        assert defaults["enabled"] is True
        assert "alertType" not in defaults

    # -----------------------------------------------------------------------
    # Customer defaults
    # -----------------------------------------------------------------------

    def test_customer_defaults_users(self):
        defaults = self.engine.get_customer_defaults("users")
        assert defaults["status"] == "active"
        assert defaults["preferences"]["language"] == "en"

    def test_customer_defaults_subscribers(self):
        defaults = self.engine.get_customer_defaults("subscribers")
        assert defaults["billing_status"] == "current"

    def test_customer_defaults_organizations(self):
        defaults = self.engine.get_customer_defaults("organizations")
        assert defaults["type"] == "business"
        assert defaults["settings"]["billing_cycle"] == "monthly"

    def test_customer_defaults_teams(self):
        defaults = self.engine.get_customer_defaults("teams")
        assert "read" in defaults["permissions"]
        assert "write" in defaults["permissions"]

    def test_customer_defaults_unknown_returns_empty(self):
        assert self.engine.get_customer_defaults("widgets") == {}

    # -----------------------------------------------------------------------
    # Source defaults
    # -----------------------------------------------------------------------

    def test_source_defaults_api(self):
        defaults = self.engine.get_source_defaults("API")
        assert defaults["type"] == "API"
        assert defaults["configuration"]["retry_count"] == 3

    def test_source_defaults_database(self):
        defaults = self.engine.get_source_defaults("DATABASE")
        assert defaults["type"] == "DATABASE"
        assert defaults["configuration"]["ssl_enabled"] is True

    def test_source_defaults_file(self):
        defaults = self.engine.get_source_defaults("FILE")
        assert defaults["configuration"]["format"] == "json"

    def test_source_defaults_stream(self):
        defaults = self.engine.get_source_defaults("STREAM")
        assert defaults["configuration"]["batch_size"] == 100

    def test_source_defaults_unknown_returns_base(self):
        defaults = self.engine.get_source_defaults("UNKNOWN")
        assert defaults["status"] == "active"
        assert "type" not in defaults

    # -----------------------------------------------------------------------
    # Subscription & pagination defaults
    # -----------------------------------------------------------------------

    def test_subscription_defaults(self):
        defaults = self.engine.get_subscription_defaults()
        assert defaults["billing_cycle"] == "monthly"
        assert defaults["auto_renew"] is True

    def test_pagination_defaults(self):
        defaults = self.engine.get_pagination_defaults()
        assert defaults["page"] == 0
        assert isinstance(defaults["size"], int)

    # -----------------------------------------------------------------------
    # Merge logic
    # -----------------------------------------------------------------------

    def test_merge_user_values_take_precedence(self):
        defaults = {"a": 1, "b": 2}
        user = {"b": 99, "c": 3}
        result = self.engine._merge_defaults(user, defaults)
        assert result["b"] == 99  # user wins
        assert result["a"] == 1   # default preserved
        assert result["c"] == 3   # user-only preserved

    def test_merge_nested_dicts(self):
        defaults = {"config": {"timeout": 30, "retries": 3}}
        user = {"config": {"timeout": 60}}
        result = self.engine._merge_defaults(user, defaults)
        assert result["config"]["timeout"] == 60
        assert result["config"]["retries"] == 3

    # -----------------------------------------------------------------------
    # apply_smart_defaults
    # -----------------------------------------------------------------------

    def test_apply_smart_defaults_alert_create(self):
        result = self.engine.apply_smart_defaults(
            "manage_alerts", "create", {"alertType": "threshold"}
        )
        assert result["enabled"] is True

    def test_apply_smart_defaults_customer_create(self):
        result = self.engine.apply_smart_defaults(
            "manage_customers", "create", {"resource_type": "users", "name": "Alice"}
        )
        assert result["status"] == "active"

    def test_apply_smart_defaults_subscription_create(self):
        result = self.engine.apply_smart_defaults(
            "manage_subscriptions", "create", {"plan": "pro"}
        )
        assert result["auto_renew"] is True

    def test_apply_smart_defaults_source_create(self):
        result = self.engine.apply_smart_defaults(
            "manage_sources", "create", {"name": "src"}
        )
        assert result["status"] == "active"

    def test_apply_smart_defaults_list_adds_pagination(self):
        result = self.engine.apply_smart_defaults(
            "manage_products", "list", {}
        )
        assert "page" in result
        assert "size" in result

    def test_apply_smart_defaults_list_preserves_user_page(self):
        result = self.engine.apply_smart_defaults(
            "manage_products", "list", {"page": 5}
        )
        assert result["page"] == 5

    def test_apply_smart_defaults_unknown_tool(self):
        """Unknown tool+action returns data unchanged (plus pagination if list)."""
        result = self.engine.apply_smart_defaults(
            "unknown_tool", "create", {"x": 1}
        )
        assert result == {"x": 1}

    # -----------------------------------------------------------------------
    # Onboarding integration
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_set_onboarding_context_explicit(self):
        ctx = {"is_first_time": True, "setup_completion": {}}
        await self.engine.set_onboarding_context(ctx)
        assert self.engine._onboarding_context == ctx

    # -----------------------------------------------------------------------
    # Onboarding tool defaults
    # -----------------------------------------------------------------------

    def test_get_onboarding_tool_defaults_welcome(self):
        d = self.engine.get_onboarding_tool_defaults("welcome_and_setup")
        assert d["show_welcome_message"] is True

    def test_get_onboarding_tool_defaults_checklist(self):
        d = self.engine.get_onboarding_tool_defaults("setup_checklist")
        assert d["highlight_priority_items"] is True

    def test_get_onboarding_tool_defaults_email(self):
        d = self.engine.get_onboarding_tool_defaults("verify_email_setup")
        assert d["validate_format"] is True

    def test_get_onboarding_tool_defaults_slack(self):
        d = self.engine.get_onboarding_tool_defaults("slack_setup_assistant")
        assert d["onboarding_mode"] is True

    def test_get_onboarding_tool_defaults_unknown(self):
        assert self.engine.get_onboarding_tool_defaults("unknown") == {}
