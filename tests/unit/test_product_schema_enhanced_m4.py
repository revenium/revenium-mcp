"""Unit tests for product_schema_enhanced.py.

Targets all missed lines (179 stmts, 0% coverage) in:
    src/revenium_mcp_server/product_schema_enhanced.py

Every test asserts specific behavioural outcomes that FAIL if the production
logic under test is removed or broken.
"""

from unittest.mock import MagicMock, patch

from src.revenium_mcp_server.product_schema_enhanced import (
    EnhancedProductSchemaDiscovery,
    FieldDocumentation,
    ProductComplexity,
    SchemaTemplate,
)


# (Dataclass/enum attribute storage and enum membership tests removed —
# those verify Python builtins, not application logic. The converters
# _field_to_dict / _template_to_dict cover the real usage path.)


# ---------------------------------------------------------------------------
# Initialization / build helpers
# ---------------------------------------------------------------------------


class TestEnhancedProductSchemaDiscoveryInit:
    """Verify __init__ builds all four internal structures."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_field_docs_is_list_of_field_documentation(self):
        assert isinstance(self.schema.field_docs, list)
        assert all(isinstance(f, FieldDocumentation) for f in self.schema.field_docs)

    def test_templates_is_list_of_schema_template(self):
        assert isinstance(self.schema.templates, list)
        assert all(isinstance(t, SchemaTemplate) for t in self.schema.templates)

    def test_business_concepts_is_dict(self):
        assert isinstance(self.schema.business_concepts, dict)
        assert "products" in self.schema.business_concepts

    def test_validation_rules_is_dict(self):
        assert isinstance(self.schema.validation_rules, dict)
        assert "product_level" in self.schema.validation_rules


# ---------------------------------------------------------------------------
# get_complete_schema
# ---------------------------------------------------------------------------


class TestGetCompleteSchema:
    """get_complete_schema returns a fully populated dict."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()
        self.result = self.schema.get_complete_schema()

    def test_schema_version_is_2(self):
        assert self.result["schema_version"] == "2.0"

    def test_complexity_levels_all_four_present(self):
        levels = self.result["complexity_levels"]
        assert set(levels) == {"simple", "intermediate", "advanced", "enterprise"}

    def test_fields_key_present_and_non_empty(self):
        assert "fields" in self.result
        assert len(self.result["fields"]) > 0

    def test_templates_key_present_and_non_empty(self):
        assert "templates" in self.result
        assert len(self.result["templates"]) > 0

    def test_workflow_guidance_present(self):
        assert "workflow_guidance" in self.result
        assert "basic_workflow" in self.result["workflow_guidance"]

    def test_core_concepts_present(self):
        assert "core_concepts" in self.result
        assert isinstance(self.result["core_concepts"], dict)

    def test_validation_rules_present(self):
        assert "validation_rules" in self.result


# ---------------------------------------------------------------------------
# get_field_documentation
# ---------------------------------------------------------------------------


class TestGetFieldDocumentation:
    """get_field_documentation returns dict for known names, None otherwise."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_known_field_name_returns_dict(self):
        result = self.schema.get_field_documentation("name")
        assert result is not None
        assert "type" in result
        assert "required" in result
        assert "description" in result

    def test_unknown_field_name_returns_none(self):
        result = self.schema.get_field_documentation("nonexistent_field_xyz")
        assert result is None

    def test_plan_type_field_returns_dict(self):
        result = self.schema.get_field_documentation("plan.type")
        assert result is not None
        assert result["required"] is True

    def test_field_dict_has_examples_key(self):
        result = self.schema.get_field_documentation("name")
        assert "examples" in result
        assert isinstance(result["examples"], list)

    def test_field_dict_has_common_mistakes_key(self):
        result = self.schema.get_field_documentation("name")
        assert "common_mistakes" in result


# ---------------------------------------------------------------------------
# get_template
# ---------------------------------------------------------------------------


class TestGetTemplate:
    """get_template returns dict for known names, None otherwise."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_known_template_returns_dict(self):
        result = self.schema.get_template("basic_subscription")
        assert result is not None
        assert "description" in result
        assert "template_data" in result

    def test_unknown_template_returns_none(self):
        result = self.schema.get_template("no_such_template_xyz")
        assert result is None

    def test_template_has_use_cases_list(self):
        result = self.schema.get_template("basic_subscription")
        assert "use_cases" in result
        assert isinstance(result["use_cases"], list)

    def test_template_has_required_customizations(self):
        result = self.schema.get_template("basic_subscription")
        assert "required_customizations" in result


# ---------------------------------------------------------------------------
# get_templates_by_complexity
# ---------------------------------------------------------------------------


class TestGetTemplatesByComplexity:
    """get_templates_by_complexity uses the internal mapping."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_all_templates_missing_returns_empty_list(self):
        """When all named templates for a complexity level are absent, result is empty."""
        with patch.object(self.schema, "get_template", return_value=None):
            result = self.schema.get_templates_by_complexity(ProductComplexity.SIMPLE)
        assert result == []

    def test_simple_complexity_attempts_correct_template_names(self):
        """Mapping for SIMPLE must target 'simple_charge' and 'basic_subscription'."""
        called_names = []

        def capture_get_template(name):
            called_names.append(name)
            return None

        with patch.object(self.schema, "get_template", side_effect=capture_get_template):
            self.schema.get_templates_by_complexity(ProductComplexity.SIMPLE)

        assert "simple_charge" in called_names
        assert "basic_subscription" in called_names

    def test_advanced_complexity_attempts_correct_template_names(self):
        called_names = []

        def capture_get_template(name):
            called_names.append(name)
            return None

        with patch.object(self.schema, "get_template", side_effect=capture_get_template):
            self.schema.get_templates_by_complexity(ProductComplexity.ADVANCED)

        assert "hybrid_pricing" in called_names
        assert "multi_component" in called_names

    def test_result_excludes_none_templates(self):
        """Templates that return None from get_template must not appear in result."""
        side_effects = [None, {"description": "found", "template_data": {}}]

        with patch.object(self.schema, "get_template", side_effect=side_effects):
            result = self.schema.get_templates_by_complexity(ProductComplexity.SIMPLE)

        # Only the non-None template should be included
        assert len(result) == 1
        assert result[0]["description"] == "found"


# ---------------------------------------------------------------------------
# suggest_template
# ---------------------------------------------------------------------------


class TestSuggestTemplate:
    """suggest_template maps requirement keywords to template names."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_usage_and_subscription_keywords_pick_hybrid_saas(self):
        """'monthly' + 'usage' → hybrid_saas route."""
        reqs = {"description": "monthly subscription with usage metering"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert result["suggested_template"]["name"] == "hybrid_saas"

    def test_usage_and_tier_keywords_pick_tiered_api(self):
        """'usage' (via 'per') + 'volume' → tiered_api route."""
        reqs = {"description": "usage based with volume tiers"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert result["suggested_template"]["name"] == "tiered_api"

    def test_usage_only_keyword_picks_simple_api_service(self):
        """'per' triggers has_usage; no subscription/tier keywords → simple_api_service."""
        reqs = {"description": "billing per API call"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert result["suggested_template"]["name"] == "simple_api_service"

    def test_subscription_only_keyword_picks_monthly_saas(self):
        """'monthly' → has_subscription; no usage/tiers → monthly_saas."""
        reqs = {"description": "monthly recurring billing subscription"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert result["suggested_template"]["name"] == "monthly_saas"

    def test_tiers_only_keyword_picks_tiered_api(self):
        """'volume' → has_tiers; no usage/subscription → tiered_api."""
        reqs = {"description": "bulk pricing with graduated volume discounts"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert result["suggested_template"]["name"] == "tiered_api"

    def test_no_keywords_defaults_to_monthly_saas(self):
        """No special keywords → default monthly_saas."""
        reqs = {"description": "a basic product"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert result["suggested_template"]["name"] == "monthly_saas"

    def test_result_contains_reasoning_and_customization_guidance(self):
        """Successful template lookup includes reasoning and customization_guidance."""
        reqs = {"description": "monthly subscription with usage metering"}
        result = self.schema.suggest_template(reqs)
        assert "suggested_template" in result
        assert "reasoning" in result
        assert "customization_guidance" in result
        assert isinstance(result["customization_guidance"], list)
        assert len(result["customization_guidance"]) > 0

    def test_import_error_returns_error_dict(self):
        """ImportError inside suggest_template falls through to error return."""
        reqs = {"description": "monthly service"}
        # Patch the module that product_schema_enhanced imports from
        with patch(
            "src.revenium_mcp_server.product_templates.ProductTemplateLibrary",
            side_effect=ImportError("module missing"),
        ):
            result = self.schema.suggest_template(reqs)
        assert "error" in result

    def test_missing_template_key_returns_error_dict(self):
        """If template_info has no 'template' key, should fall through to error."""
        lib = MagicMock()
        lib.get_template.return_value = {"description": "no template key"}
        with patch(
            "src.revenium_mcp_server.product_templates.ProductTemplateLibrary",
            return_value=lib,
        ):
            result = self.schema.suggest_template({"description": "something"})
        assert "error" in result


# ---------------------------------------------------------------------------
# validate_product_structure
# ---------------------------------------------------------------------------


class TestValidateProductStructure:
    """validate_product_structure exercises all validation branches."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_valid_product_passes(self):
        product = {
            "name": "My Product",
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "period": "MONTH",
                "tiers": [{"name": "Basic", "up_to": None, "unit_amount": "10.00"}],
            },
        }
        result = self.schema.validate_product_structure(product)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_name_produces_error(self):
        product = {"version": "1.0.0", "plan": {}}
        result = self.schema.validate_product_structure(product)
        assert result["valid"] is False
        error_fields = [e["field"] for e in result["errors"]]
        assert "name" in error_fields

    def test_missing_version_produces_error(self):
        product = {"name": "X", "plan": {}}
        result = self.schema.validate_product_structure(product)
        error_fields = [e["field"] for e in result["errors"]]
        assert "version" in error_fields

    def test_missing_plan_produces_error(self):
        product = {"name": "X", "version": "1.0.0"}
        result = self.schema.validate_product_structure(product)
        error_fields = [e["field"] for e in result["errors"]]
        assert "plan" in error_fields

    def test_error_includes_fix_and_example(self):
        product = {}
        result = self.schema.validate_product_structure(product)
        for error in result["errors"]:
            assert "fix" in error
            assert "example" in error

    def test_completeness_score_zero_for_empty_product(self):
        result = self.schema.validate_product_structure({})
        assert result["completeness_score"] == 0.0

    def test_completeness_score_increases_with_more_fields(self):
        partial = {"name": "X", "version": "1.0.0"}
        full = {
            "name": "X",
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "name": "Plan",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [{"up_to": None, "unit_amount": "10.00"}],
            },
        }
        partial_score = self.schema.validate_product_structure(partial)["completeness_score"]
        full_score = self.schema.validate_product_structure(full)["completeness_score"]
        assert full_score > partial_score

    def test_complexity_assessment_returned(self):
        product = {"name": "X", "version": "1.0.0", "plan": {}}
        result = self.schema.validate_product_structure(product)
        assert "complexity_assessment" in result

    def test_plan_without_type_adds_error(self):
        product = {
            "name": "X",
            "version": "1.0.0",
            "plan": {"tiers": [{"up_to": None, "unit_amount": "5.00"}]},
        }
        result = self.schema.validate_product_structure(product)
        error_fields = [e["field"] for e in result["errors"]]
        assert "plan.type" in error_fields

    def test_subscription_plan_without_period_adds_error(self):
        product = {
            "name": "X",
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "tiers": [{"up_to": None, "unit_amount": "5.00"}],
            },
        }
        result = self.schema.validate_product_structure(product)
        error_fields = [e["field"] for e in result["errors"]]
        assert "plan.period" in error_fields

    def test_plan_without_tiers_adds_error(self):
        product = {
            "name": "X",
            "version": "1.0.0",
            "plan": {"type": "SUBSCRIPTION", "period": "MONTH"},
        }
        result = self.schema.validate_product_structure(product)
        error_fields = [e["field"] for e in result["errors"]]
        assert "plan.tiers" in error_fields


# ---------------------------------------------------------------------------
# _assess_complexity
# ---------------------------------------------------------------------------


class TestAssessComplexity:
    """_assess_complexity maps features to ProductComplexity levels."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_empty_product_is_simple(self):
        assert self.schema._assess_complexity({}) == ProductComplexity.SIMPLE

    def test_single_tier_is_simple(self):
        product = {"plan": {"tiers": [{"up_to": None}]}}
        assert self.schema._assess_complexity(product) == ProductComplexity.SIMPLE

    def test_two_tiers_is_exactly_intermediate(self):
        """2 tiers adds exactly 1 complexity point → INTERMEDIATE (score 1, threshold >=1)."""
        product = {"plan": {"tiers": [{"up_to": 100}, {"up_to": None}]}}
        result = self.schema._assess_complexity(product)
        assert result == ProductComplexity.INTERMEDIATE

    def test_rating_aggregations_raises_complexity(self):
        product = {
            "plan": {
                "tiers": [{"up_to": None}],
                "rating_aggregations": [{"name": "API Calls"}],
            }
        }
        result = self.schema._assess_complexity(product)
        # rating_aggregations add 2 points → at least ADVANCED
        assert result in (ProductComplexity.ADVANCED, ProductComplexity.ENTERPRISE)

    def test_many_features_produce_enterprise(self):
        product = {
            "plan": {
                "tiers": [{"up_to": 100}, {"up_to": None}],  # +1
                "rating_aggregations": [{"name": "A"}],  # +2
                "elements": [{"name": "E1"}, {"name": "E2"}],  # +1
                "setup_fees": [{"amount": "5.00"}],  # +1
            },
            "notification_addresses_on_invoice": ["a@b.com", "c@d.com", "e@f.com"],  # +1
        }
        result = self.schema._assess_complexity(product)
        assert result == ProductComplexity.ENTERPRISE


# ---------------------------------------------------------------------------
# _calculate_completeness_score
# ---------------------------------------------------------------------------


class TestCalculateCompletenessScore:
    """_calculate_completeness_score returns a float 0.0–1.0."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_empty_product_returns_zero(self):
        assert self.schema._calculate_completeness_score({}) == 0.0

    def test_all_core_fields_present_increases_score(self):
        product = {"name": "X", "version": "1.0.0", "plan": {"type": "SUBSCRIPTION"}}
        score = self.schema._calculate_completeness_score(product)
        assert score > 0.0

    def test_optional_fields_increase_score(self):
        base = {"name": "X", "version": "1.0.0", "plan": {"type": "SUBSCRIPTION"}}
        with_optional = {
            "name": "X",
            "version": "1.0.0",
            "plan": {"type": "SUBSCRIPTION"},
            "description": "desc",
            "tags": ["tag1"],
            "notification_addresses_on_invoice": ["a@b.com"],
        }
        base_score = self.schema._calculate_completeness_score(base)
        full_score = self.schema._calculate_completeness_score(with_optional)
        assert full_score > base_score

    def test_score_is_between_zero_and_one(self):
        product = {
            "name": "X",
            "version": "1.0.0",
            "plan": {
                "type": "SUBSCRIPTION",
                "name": "Plan",
                "currency": "USD",
                "tiers": [{"up_to": None}],
            },
            "description": "d",
            "tags": ["t"],
            "notification_addresses_on_invoice": ["x@y.com"],
        }
        score = self.schema._calculate_completeness_score(product)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# get_business_guidance
# ---------------------------------------------------------------------------


class TestGetBusinessGuidance:
    """get_business_guidance returns general principles and optionally domain-specific."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_no_domain_returns_general_guidance(self):
        result = self.schema.get_business_guidance()
        assert "general_principles" in result
        assert "common_patterns" in result
        assert "domain_specific" not in result

    def test_saas_domain_adds_domain_specific_key(self):
        result = self.schema.get_business_guidance(domain="saas")
        assert "domain_specific" in result
        assert "recommended_model" in result["domain_specific"]

    def test_api_domain_returns_api_specific_guidance(self):
        result = self.schema.get_business_guidance(domain="api")
        assert result["domain_specific"]["recommended_model"] == "Usage-based per API call"

    def test_shipping_domain_returns_shipping_specific_guidance(self):
        result = self.schema.get_business_guidance(domain="shipping")
        ds = result["domain_specific"]
        assert "packages_shipped" in ds["common_metrics"]

    def test_unknown_domain_returns_fallback_guidance(self):
        result = self.schema.get_business_guidance(domain="unknown_domain_xyz")
        assert "domain_specific" in result
        assert "pricing_tips" in result["domain_specific"]


# ---------------------------------------------------------------------------
# _explain_template_choice
# ---------------------------------------------------------------------------


class TestExplainTemplateChoice:
    """_explain_template_choice returns known strings for known template names."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_monthly_saas_explanation_mentions_subscription(self):
        """The monthly_saas explanation must specifically mention 'subscription'."""
        result = self.schema._explain_template_choice({}, "monthly_saas")
        # Production code: "Chosen for recurring subscription billing..."
        assert "subscription" in result.lower()

    def test_unknown_template_returns_generic_explanation(self):
        result = self.schema._explain_template_choice({}, "completely_unknown")
        assert "requirements" in result.lower()

    def test_simple_api_service_explanation_mentions_api(self):
        """The simple_api_service explanation must specifically mention 'api'."""
        result = self.schema._explain_template_choice({}, "simple_api_service")
        # Production code: "Chosen for API services with per-call pricing..."
        assert "api" in result.lower()

    def test_tiered_api_explanation_mentions_volume(self):
        """The tiered_api explanation must specifically mention 'volume'."""
        result = self.schema._explain_template_choice({}, "tiered_api")
        # Production code: "Chosen for API services with volume discounts..."
        assert "volume" in result.lower()

    def test_hybrid_saas_explanation_mentions_subscription_and_usage(self):
        """The hybrid_saas explanation must mention both concepts."""
        result = self.schema._explain_template_choice({}, "hybrid_saas")
        # Production code: "Chosen for combining subscription base with usage-based overages"
        assert "subscription" in result.lower()
        assert "usage" in result.lower()


# ---------------------------------------------------------------------------
# _get_customization_guidance
# ---------------------------------------------------------------------------


class TestGetCustomizationGuidance:
    """_get_customization_guidance appends template-specific hints to base list."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_base_guidance_always_present(self):
        result = self.schema._get_customization_guidance("unknown_template")
        assert any("name" in g.lower() for g in result)

    def test_simple_api_service_adds_specific_guidance(self):
        result = self.schema._get_customization_guidance("simple_api_service")
        combined = " ".join(result).lower()
        assert "usage" in combined or "metric" in combined

    def test_monthly_saas_adds_billing_period_guidance(self):
        result = self.schema._get_customization_guidance("monthly_saas")
        combined = " ".join(result).lower()
        assert "billing" in combined or "period" in combined or "annual" in combined

    def test_tiered_api_adds_tier_guidance(self):
        result = self.schema._get_customization_guidance("tiered_api")
        combined = " ".join(result).lower()
        assert "tier" in combined or "volume" in combined

    def test_hybrid_saas_adds_subscription_and_usage_guidance(self):
        result = self.schema._get_customization_guidance("hybrid_saas")
        combined = " ".join(result).lower()
        assert "subscription" in combined or "overage" in combined

    def test_shipping_service_adds_shipping_guidance(self):
        result = self.schema._get_customization_guidance("shipping_service")
        combined = " ".join(result).lower()
        assert "weight" in combined or "shipping" in combined or "rate" in combined

    def test_result_is_list_of_strings(self):
        result = self.schema._get_customization_guidance("monthly_saas")
        assert isinstance(result, list)
        assert all(isinstance(g, str) for g in result)


# ---------------------------------------------------------------------------
# _build_business_concepts
# ---------------------------------------------------------------------------


class TestBuildBusinessConcepts:
    """Business concepts dict must contain all key domains."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_required_concept_keys_present(self):
        for key in (
            "products",
            "plans",
            "metering_elements",
            "rating_aggregations",
            "tiers",
            "billing_periods",
        ):
            assert key in self.schema.business_concepts, f"Missing concept: {key}"

    def test_aggregation_types_lists_sum_and_count(self):
        agg_text = self.schema.business_concepts.get("aggregation_types", "")
        assert "SUM" in agg_text
        assert "COUNT" in agg_text


# ---------------------------------------------------------------------------
# _build_validation_rules
# ---------------------------------------------------------------------------


class TestBuildValidationRules:
    """Validation rules must cover four schema levels."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_four_rule_groups_present(self):
        for group in ("product_level", "plan_level", "tier_level", "aggregation_level"):
            assert group in self.schema.validation_rules, f"Missing group: {group}"

    def test_each_group_is_non_empty_list(self):
        for rules in self.schema.validation_rules.values():
            assert isinstance(rules, list)
            assert len(rules) > 0


# ---------------------------------------------------------------------------
# _get_workflow_guidance
# ---------------------------------------------------------------------------


class TestGetWorkflowGuidance:
    """_get_workflow_guidance must contain all required workflow keys."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()
        self.guidance = self.schema._get_workflow_guidance()

    def test_basic_workflow_is_list(self):
        assert isinstance(self.guidance["basic_workflow"], list)
        assert len(self.guidance["basic_workflow"]) > 0

    def test_simple_product_workflow_present(self):
        assert "simple_product_workflow" in self.guidance

    def test_usage_based_workflow_present(self):
        assert "usage_based_workflow" in self.guidance

    def test_decision_points_present(self):
        assert "decision_points" in self.guidance
        dp = self.guidance["decision_points"]
        assert "aggregation_types" in dp

    def test_common_workflows_present(self):
        assert "common_workflows" in self.guidance
        cw = self.guidance["common_workflows"]
        assert "simple_saas_subscription" in cw

    def test_best_practices_present(self):
        assert "best_practices" in self.guidance
        assert isinstance(self.guidance["best_practices"], list)


# ---------------------------------------------------------------------------
# _field_to_dict and _template_to_dict
# ---------------------------------------------------------------------------


class TestPrivateConverters:
    """_field_to_dict and _template_to_dict must map dataclass → dict correctly."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_field_to_dict_keys(self):
        fd = FieldDocumentation(
            name="x",
            type="string",
            required=False,
            description="d",
            business_context="bc",
            examples=["e"],
            validation_rules=["r"],
            related_fields=["f"],
            common_mistakes=["m"],
        )
        result = self.schema._field_to_dict(fd)
        for key in ("type", "required", "description", "business_context", "examples",
                    "validation_rules", "related_fields", "common_mistakes"):
            assert key in result, f"Missing key: {key}"

    def test_field_to_dict_values(self):
        fd = FieldDocumentation(
            name="y",
            type="number",
            required=True,
            description="desc",
            business_context="ctx",
            examples=[1, 2],
            validation_rules=["positive"],
            related_fields=["z"],
            common_mistakes=["negative"],
        )
        result = self.schema._field_to_dict(fd)
        assert result["type"] == "number"
        assert result["required"] is True
        assert result["examples"] == [1, 2]

    def test_template_to_dict_keys(self):
        tmpl = SchemaTemplate(
            name="t",
            description="desc",
            use_cases=["u"],
            template_data={"k": "v"},
            required_customizations=["r"],
            optional_customizations=["o"],
        )
        result = self.schema._template_to_dict(tmpl)
        for key in ("description", "use_cases", "template_data",
                    "required_customizations", "optional_customizations"):
            assert key in result, f"Missing key: {key}"

    def test_template_to_dict_does_not_include_name(self):
        tmpl = SchemaTemplate(
            name="t",
            description="desc",
            use_cases=[],
            template_data={},
            required_customizations=[],
            optional_customizations=[],
        )
        result = self.schema._template_to_dict(tmpl)
        # 'name' is the dict key in get_complete_schema, not a value in the inner dict
        assert "name" not in result


# ---------------------------------------------------------------------------
# _get_field_example
# ---------------------------------------------------------------------------


class TestGetFieldExample:
    """_get_field_example returns known values for documented fields."""

    def setup_method(self):
        self.schema = EnhancedProductSchemaDiscovery()

    def test_name_example_is_string(self):
        result = self.schema._get_field_example("name")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_version_example_looks_like_semver(self):
        result = self.schema._get_field_example("version")
        parts = str(result).split(".")
        assert len(parts) == 3

    def test_plan_example_is_dict_with_type(self):
        result = self.schema._get_field_example("plan")
        assert isinstance(result, dict)
        assert "type" in result

    def test_unknown_field_returns_generic_string(self):
        result = self.schema._get_field_example("no_such_field_xyz")
        assert result == "Example value"
