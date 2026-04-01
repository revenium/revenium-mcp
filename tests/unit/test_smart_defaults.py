"""Unit tests for SmartDefaultsEngine — product/alert/customer/source defaults and merging."""

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.smart_defaults import SmartDefaultsEngine


class TestSmartDefaultsEngine:
    """Test SmartDefaultsEngine default value generation and merging."""

    def setup_method(self):
        self.engine = SmartDefaultsEngine()

    # -----------------------------------------------------------------------
    # Product defaults
    # -----------------------------------------------------------------------

    def test_product_defaults_simple(self):
        defaults = self.engine.get_product_defaults("simple")
        assert defaults["version"] == "1.0.0"
        assert defaults["published"] is True
        assert defaults["plan"]["type"] == "CHARGE"

    def test_product_defaults_subscription(self):
        defaults = self.engine.get_product_defaults("subscription")
        assert defaults["plan"]["type"] == "SUBSCRIPTION"
        assert defaults["plan"]["period"] == "MONTH"

    def test_product_defaults_usage_based(self):
        defaults = self.engine.get_product_defaults("usage_based")
        assert defaults["plan"]["type"] == "USAGE"
        assert defaults["plan"]["graduated"] is True
        assert len(defaults["plan"]["tiers"]) == 3

    def test_product_defaults_unknown_type_returns_base(self):
        defaults = self.engine.get_product_defaults("unknown_type")
        assert "version" in defaults
        assert "plan" not in defaults

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

    def test_apply_smart_defaults_product_create(self):
        result = self.engine.apply_smart_defaults(
            "manage_products", "create", {"name": "My Product"}
        )
        assert result["name"] == "My Product"
        assert "version" in result

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
    # _detect_product_type
    # -----------------------------------------------------------------------

    def test_detect_product_type_subscription(self):
        assert self.engine._detect_product_type({"plan": {"type": "SUBSCRIPTION"}}) == "subscription"

    def test_detect_product_type_usage(self):
        assert self.engine._detect_product_type({"plan": {"type": "USAGE"}}) == "usage_based"

    def test_detect_product_type_simple_by_default(self):
        assert self.engine._detect_product_type({}) == "simple"

    # -----------------------------------------------------------------------
    # Onboarding integration
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_set_onboarding_context_explicit(self):
        ctx = {"is_first_time": True, "setup_completion": {}}
        await self.engine.set_onboarding_context(ctx)
        assert self.engine._onboarding_context == ctx

    def test_get_onboarding_enhanced_defaults_no_context(self):
        """Without onboarding context, falls back to standard defaults."""
        result = self.engine.get_onboarding_enhanced_defaults(
            "manage_products", "create", {"name": "Test"}
        )
        assert "version" in result

    def test_get_onboarding_enhanced_defaults_with_context(self):
        self.engine._onboarding_context = {
            "is_first_time": True,
            "setup_completion": {"email_configured": True},
        }
        result = self.engine.get_onboarding_enhanced_defaults(
            "manage_products", "create", {"name": "My Prod"}
        )
        assert "description" in result  # enhanced for onboarding

    # -----------------------------------------------------------------------
    # Onboarding-specific enhancements
    # -----------------------------------------------------------------------

    def test_enhance_alert_for_onboarding_threshold(self):
        self.engine._onboarding_context = {
            "is_first_time": True,
            "setup_completion": {},
        }
        alert_data = self.engine.get_alert_defaults("threshold")
        enhanced = self.engine._enhance_alert_for_onboarding(alert_data)
        assert "First Alert" in enhanced.get("description", "")

    def test_enhance_alert_for_onboarding_cumulative(self):
        self.engine._onboarding_context = {
            "is_first_time": True,
            "setup_completion": {},
        }
        alert_data = self.engine.get_alert_defaults("cumulative_usage")
        enhanced = self.engine._enhance_alert_for_onboarding(alert_data)
        assert "Budget" in enhanced.get("description", "")

    def test_enhance_product_for_onboarding_adds_defaults(self):
        enhanced = self.engine._enhance_product_for_onboarding({})
        assert enhanced.get("name") == "Starter Product"
        assert "onboarding" in enhanced.get("description", "").lower()

    # -----------------------------------------------------------------------
    # Completion calculation
    # -----------------------------------------------------------------------

    def test_calculate_completion_percentage_all_done(self):
        pct = self.engine._calculate_completion_percentage(
            {"a": True, "b": True, "c": True}
        )
        assert pct == pytest.approx(100.0)

    def test_calculate_completion_percentage_half(self):
        pct = self.engine._calculate_completion_percentage(
            {"a": True, "b": False}
        )
        assert pct == pytest.approx(50.0)

    def test_calculate_completion_percentage_empty(self):
        assert self.engine._calculate_completion_percentage({}) == 0.0

    # -----------------------------------------------------------------------
    # Priority setup items
    # -----------------------------------------------------------------------

    def test_get_priority_setup_items_all_missing(self):
        items = self.engine._get_priority_setup_items({})
        assert "API Key Configuration" in items
        assert "Team ID Configuration" in items
        assert "Email Notifications" in items

    def test_get_priority_setup_items_all_set(self):
        items = self.engine._get_priority_setup_items(
            {"api_key_configured": True, "team_id_configured": True, "email_configured": True}
        )
        assert items == []

    # -----------------------------------------------------------------------
    # Personalized recommendations
    # -----------------------------------------------------------------------

    def test_get_personalized_recommendations_no_context(self):
        self.engine._onboarding_context = None
        assert self.engine._get_personalized_recommendations() == []

    def test_get_personalized_recommendations_missing_key(self):
        self.engine._onboarding_context = {"setup_completion": {}}
        recs = self.engine._get_personalized_recommendations()
        assert any("API key" in r for r in recs)

    def test_get_personalized_recommendations_all_configured(self):
        self.engine._onboarding_context = {
            "setup_completion": {
                "api_key_configured": True,
                "email_configured": True,
                "slack_configured": True,
            }
        }
        recs = self.engine._get_personalized_recommendations()
        assert any("alert" in r.lower() for r in recs)

    # -----------------------------------------------------------------------
    # Suggested email
    # -----------------------------------------------------------------------

    def test_get_suggested_email_dummy(self):
        self.engine.env_defaults["notification_email"] = "dummy@email.com"
        assert self.engine._get_suggested_email() is None

    def test_get_suggested_email_valid(self):
        self.engine.env_defaults["notification_email"] = "admin@corp.com"
        assert self.engine._get_suggested_email() == "admin@corp.com"

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
