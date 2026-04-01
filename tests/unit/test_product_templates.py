"""Unit tests for product_templates module."""

import pytest

from src.revenium_mcp_server.product_templates import (
    ProductExample,
    ProductTemplateLibrary,
)


class TestProductTemplateLibrary:
    """Tests for ProductTemplateLibrary."""

    def setup_method(self):
        """Set up a fresh library for each test."""
        self.library = ProductTemplateLibrary()

    def test_get_all_templates_returns_non_empty_dict(self):
        """Library should contain multiple templates."""
        templates = self.library.get_all_templates()
        assert isinstance(templates, dict)
        assert len(templates) >= 3

    def test_get_template_by_name(self):
        """Should retrieve a specific template by name."""
        template = self.library.get_template("simple_api_service")
        assert template != {}
        assert "template" in template
        assert "customization_guide" in template

    def test_get_template_nonexistent(self):
        """Should return empty dict for unknown template name."""
        template = self.library.get_template("nonexistent_template")
        assert template == {}

    def test_templates_have_subscription_plan_type(self):
        """All templates should use SUBSCRIPTION plan type (not deprecated CHARGE)."""
        templates = self.library.get_all_templates()
        for name, template in templates.items():
            plan_type = template["template"]["plan"]["type"]
            assert plan_type == "SUBSCRIPTION", (
                f"Template '{name}' uses deprecated plan type '{plan_type}'"
            )

    def test_get_examples_by_category_simple(self):
        """Should filter examples by complexity category."""
        simple_examples = self.library.get_examples_by_category("simple")
        assert len(simple_examples) >= 1
        for ex in simple_examples:
            assert ex.complexity == "simple"

    def test_get_examples_by_category_nonexistent(self):
        """Should return empty list for unknown category."""
        examples = self.library.get_examples_by_category("nonexistent")
        assert examples == []

    def test_get_example_by_name(self):
        """Should retrieve a specific example by name."""
        example = self.library.get_example("simple_charge_example")
        assert example is not None
        assert isinstance(example, ProductExample)
        assert example.name == "simple_charge_example"

    def test_get_example_nonexistent(self):
        """Should return None for unknown example name."""
        example = self.library.get_example("nonexistent_example")
        assert example is None

    def test_examples_have_required_fields(self):
        """All examples should have data, explanation, and customization_points."""
        for example in self.library.examples:
            assert isinstance(example.data, dict)
            assert isinstance(example.explanation, str)
            assert isinstance(example.customization_points, list)
            assert len(example.customization_points) > 0

    def test_template_customization_guides_are_lists(self):
        """Each template should have a list of customization guide strings."""
        for name, template in self.library.get_all_templates().items():
            assert isinstance(template["customization_guide"], list)
            assert all(isinstance(s, str) for s in template["customization_guide"])
