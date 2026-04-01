"""Unit tests for relationships.service module.

Tests ResourceRelationshipService action routing and response formatting
for each supported action.
"""

import pytest

from src.revenium_mcp_server.relationships.service import ResourceRelationshipService
from src.revenium_mcp_server.relationships.engine import ResourceRelationshipEngine


@pytest.fixture
def service():
    """Create a fresh service with its own engine."""
    svc = ResourceRelationshipService()
    svc.engine = ResourceRelationshipEngine()
    return svc


class TestActionRouting:
    """Test that actions are routed to correct handlers."""

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, service):
        """Unknown action returns error with supported actions list."""
        result = await service.handle_relationship_action("nonexistent", {})
        assert len(result) == 1
        assert "Unknown relationship action" in result[0].text
        assert "get_resource_relationships" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capabilities_action(self, service):
        """get_capabilities returns capability description."""
        result = await service.handle_relationship_action("get_capabilities", {})
        assert len(result) == 1
        assert "Resource Relationship Service" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_action(self, service):
        """get_examples returns usage examples."""
        result = await service.handle_relationship_action("get_examples", {})
        assert len(result) == 1
        assert "Examples" in result[0].text


class TestGetResourceRelationships:
    """Test get_resource_relationships action."""

    @pytest.mark.asyncio
    async def test_missing_params_returns_error(self, service):
        """Missing resource_type/resource_id returns error."""
        result = await service.handle_relationship_action(
            "get_resource_relationships", {}
        )
        assert "resource_type" in result[0].text

    @pytest.mark.asyncio
    async def test_nonexistent_resource_returns_error(self, service):
        """Non-existent resource returns error message."""
        result = await service.handle_relationship_action(
            "get_resource_relationships",
            {"resource_type": "products", "resource_id": "missing"},
        )
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_existing_resource_returns_relationships(self, service):
        """Existing resource returns relationship info."""
        await service.engine.add_resource("products", {
            "id": "p1", "name": "Widget", "organization_id": "org1"
        })
        result = await service.handle_relationship_action(
            "get_resource_relationships",
            {"resource_type": "products", "resource_id": "p1"},
        )
        text = result[0].text
        assert "Resource Relationships" in text
        assert "p1" in text


class TestFindRelatedResources:
    """Test find_related_resources action."""

    @pytest.mark.asyncio
    async def test_missing_params_returns_error(self, service):
        """Missing params returns error."""
        result = await service.handle_relationship_action(
            "find_related_resources", {}
        )
        assert "resource_type" in result[0].text

    @pytest.mark.asyncio
    async def test_finds_related(self, service):
        """Related resources are found for existing resource."""
        await service.engine.add_resource("products", {
            "id": "p1", "organization_id": "org1"
        })
        result = await service.handle_relationship_action(
            "find_related_resources",
            {"resource_type": "products", "resource_id": "p1"},
        )
        text = result[0].text
        assert "Related Resources" in text

    @pytest.mark.asyncio
    async def test_with_relationship_type_filter(self, service):
        """Relationship type filter is applied and shown."""
        await service.engine.add_resource("products", {
            "id": "p1", "organization_id": "org1"
        })
        result = await service.handle_relationship_action(
            "find_related_resources",
            {
                "resource_type": "products",
                "resource_id": "p1",
                "relationship_types": ["belongs_to"],
            },
        )
        text = result[0].text
        assert "belongs_to" in text


class TestValidateCrossResourceOperation:
    """Test validate_cross_resource_operation action."""

    @pytest.mark.asyncio
    async def test_missing_operation_returns_error(self, service):
        """Missing operation parameter returns error."""
        result = await service.handle_relationship_action(
            "validate_cross_resource_operation", {}
        )
        assert "operation parameter is required" in result[0].text

    @pytest.mark.asyncio
    async def test_valid_operation(self, service):
        """Valid operation returns validation result."""
        result = await service.handle_relationship_action(
            "validate_cross_resource_operation",
            {"operation": {"resource_type": "products", "resource_data": {"name": "Good Product"}}},
        )
        text = result[0].text
        assert "Validation" in text

    @pytest.mark.asyncio
    async def test_invalid_operation_shows_errors(self, service):
        """Invalid operation shows validation errors."""
        result = await service.handle_relationship_action(
            "validate_cross_resource_operation",
            {"operation": {"resource_type": "products", "resource_data": {"name": "ab"}}},
        )
        text = result[0].text
        assert "FAILED" in text
        assert "Errors" in text


class TestGetDependencyGraph:
    """Test get_dependency_graph action."""

    @pytest.mark.asyncio
    async def test_returns_graph_stats(self, service):
        """Dependency graph returns statistics."""
        result = await service.handle_relationship_action("get_dependency_graph", {})
        text = result[0].text
        assert "Dependency Graph" in text
        assert "Total Resources" in text


class TestGetRelationshipPatterns:
    """Test get_relationship_patterns action."""

    @pytest.mark.asyncio
    async def test_returns_patterns(self, service):
        """Relationship patterns returns pattern info."""
        result = await service.handle_relationship_action("get_relationship_patterns", {})
        text = result[0].text
        assert "Relationship Patterns" in text
        assert "Total Patterns" in text


class TestAnalyzeResourceImpact:
    """Test analyze_resource_impact action."""

    @pytest.mark.asyncio
    async def test_missing_params(self, service):
        """Missing params returns error."""
        result = await service.handle_relationship_action(
            "analyze_resource_impact", {}
        )
        assert "resource_type" in result[0].text

    @pytest.mark.asyncio
    async def test_existing_resource(self, service):
        """Impact analysis for existing resource returns results."""
        await service.engine.add_resource("products", {
            "id": "p1", "organization_id": "org1"
        })
        result = await service.handle_relationship_action(
            "analyze_resource_impact",
            {"resource_type": "products", "resource_id": "p1", "operation": "delete"},
        )
        text = result[0].text
        assert "Impact Analysis" in text

    @pytest.mark.asyncio
    async def test_missing_resource(self, service):
        """Impact analysis for missing resource returns error."""
        result = await service.handle_relationship_action(
            "analyze_resource_impact",
            {"resource_type": "products", "resource_id": "missing"},
        )
        assert "Error" in result[0].text


class TestGetNavigationPath:
    """Test get_navigation_path action."""

    @pytest.mark.asyncio
    async def test_missing_params(self, service):
        """Missing params returns error."""
        result = await service.handle_relationship_action(
            "get_navigation_path", {}
        )
        assert "required" in result[0].text

    @pytest.mark.asyncio
    async def test_path_found(self, service):
        """Path between connected resources is shown."""
        await service.engine.add_resource("products", {
            "id": "p1", "organization_id": "org1"
        })
        result = await service.handle_relationship_action(
            "get_navigation_path",
            {
                "from_resource_type": "products",
                "from_resource_id": "p1",
                "to_resource_type": "organizations",
                "to_resource_id": "org1",
            },
        )
        text = result[0].text
        assert "Navigation Path" in text
        assert "Path found" in text or "path found" in text.lower()

    @pytest.mark.asyncio
    async def test_no_path_found(self, service):
        """No path between disconnected resources is reported."""
        await service.engine.add_resource("products", {"id": "p1"})
        await service.engine.add_resource("alerts", {"id": "a1"})
        result = await service.handle_relationship_action(
            "get_navigation_path",
            {
                "from_resource_type": "products",
                "from_resource_id": "p1",
                "to_resource_type": "alerts",
                "to_resource_id": "a1",
            },
        )
        text = result[0].text
        assert "No path found" in text


class TestAddResource:
    """Test add_resource action."""

    @pytest.mark.asyncio
    async def test_missing_params(self, service):
        """Missing params returns error."""
        result = await service.handle_relationship_action("add_resource", {})
        assert "resource_type" in result[0].text

    @pytest.mark.asyncio
    async def test_add_resource_success(self, service):
        """Successfully adding a resource shows confirmation."""
        result = await service.handle_relationship_action(
            "add_resource",
            {
                "resource_type": "products",
                "resource_data": {"id": "p1", "name": "Widget", "organization_id": "org1"},
            },
        )
        text = result[0].text
        assert "Resource Added" in text
        assert "p1" in text

    @pytest.mark.asyncio
    async def test_add_resource_with_many_relationships(self, service):
        """Adding resource with many relationships truncates display."""
        result = await service.handle_relationship_action(
            "add_resource",
            {
                "resource_type": "products",
                "resource_data": {
                    "id": "p1",
                    "source_ids": [f"s{i}" for i in range(10)],
                    "organization_id": "org1",
                    "team_id": "t1",
                },
            },
        )
        text = result[0].text
        assert "Resource Added" in text


class TestExceptionHandling:
    """Test error handling in action dispatch."""

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error_message(self, service):
        """Exception in handler produces error TextContent."""
        # Force engine to be broken
        service.engine = None
        result = await service.handle_relationship_action(
            "get_dependency_graph", {}
        )
        assert "Relationship Error" in result[0].text
