"""Unit tests for relationships.engine module.

Tests ResourceRelationshipEngine including resource addition, relationship
queries, cross-resource validation, dependency graph, impact analysis,
and navigation path finding.
"""

import pytest

from src.revenium_mcp_server.relationships.engine import ResourceRelationshipEngine


@pytest.fixture
def engine():
    """Create a fresh ResourceRelationshipEngine."""
    return ResourceRelationshipEngine()


class TestEngineInitialization:
    """Test engine initialization."""

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, engine):
        """Multiple initialize calls are safe."""
        await engine.initialize()
        await engine.initialize()
        assert engine._initialized is True


class TestAddResource:
    """Test adding resources to the engine."""

    @pytest.mark.asyncio
    async def test_add_resource_success(self, engine):
        """Adding a valid resource returns success."""
        result = await engine.add_resource("products", {
            "id": "p1",
            "name": "Widget",
            "organization_id": "org1",
        })
        assert result["success"] is True
        assert result["resource_type"] == "products"
        assert result["resource_id"] == "p1"
        assert "relationships" in result

    @pytest.mark.asyncio
    async def test_add_resource_uses_resource_id_fallback(self, engine):
        """Falls back to resource_id when id is absent."""
        result = await engine.add_resource("products", {"resource_id": "r1"})
        assert result["success"] is True
        assert result["resource_id"] == "r1"


class TestGetResourceRelationships:
    """Test querying resource relationships."""

    @pytest.mark.asyncio
    async def test_get_relationships_for_added_resource(self, engine):
        """Getting relationships for an added resource returns data."""
        await engine.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = await engine.get_resource_relationships("products", "p1")
        assert result["success"] is True
        assert "relationships" in result

    @pytest.mark.asyncio
    async def test_get_relationships_for_missing_resource(self, engine):
        """Getting relationships for missing resource returns error."""
        result = await engine.get_resource_relationships("products", "missing")
        assert result["success"] is False
        assert "error" in result


class TestFindRelatedResources:
    """Test finding related resources."""

    @pytest.mark.asyncio
    async def test_find_related_for_existing(self, engine):
        """Finding related resources for existing resource succeeds."""
        await engine.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = await engine.find_related_resources("products", "p1")
        assert result["success"] is True
        assert "related_resources" in result

    @pytest.mark.asyncio
    async def test_find_related_for_missing(self, engine):
        """Finding related resources for missing resource returns error."""
        result = await engine.find_related_resources("products", "missing")
        assert result["success"] is False


class TestValidateCrossResourceOperation:
    """Test cross-resource operation validation."""

    @pytest.mark.asyncio
    async def test_validate_valid_operation(self, engine):
        """Valid operation passes validation."""
        result = await engine.validate_cross_resource_operation({
            "resource_type": "products",
            "resource_data": {"name": "Good Product"},
        })
        assert result["success"] is True
        assert result["validation_result"]["validation_passed"] is True

    @pytest.mark.asyncio
    async def test_validate_invalid_operation(self, engine):
        """Invalid operation fails validation."""
        result = await engine.validate_cross_resource_operation({
            "resource_type": "products",
            "resource_data": {"name": "ab"},
        })
        assert result["success"] is True
        assert result["validation_result"]["validation_passed"] is False


class TestDependencyGraph:
    """Test dependency graph retrieval."""

    @pytest.mark.asyncio
    async def test_get_empty_dependency_graph(self, engine):
        """Empty engine returns empty graph."""
        result = await engine.get_dependency_graph()
        assert result["success"] is True
        assert result["graph"]["node_count"] == 0

    @pytest.mark.asyncio
    async def test_get_populated_dependency_graph(self, engine):
        """Graph contains added resources."""
        await engine.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = await engine.get_dependency_graph()
        assert result["success"] is True
        assert result["graph"]["node_count"] > 0


class TestRelationshipPatterns:
    """Test relationship pattern retrieval."""

    @pytest.mark.asyncio
    async def test_get_patterns(self, engine):
        """Patterns include known resource types."""
        result = await engine.get_relationship_patterns()
        assert result["success"] is True
        assert "products" in result["patterns"]
        assert result["total_patterns"] > 0


class TestImpactAnalysis:
    """Test resource impact analysis."""

    @pytest.mark.asyncio
    async def test_analyze_impact_existing_resource(self, engine):
        """Impact analysis for existing resource returns analysis."""
        await engine.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = await engine.analyze_resource_impact("products", "p1", "delete")
        assert result["success"] is True
        assert "impact_analysis" in result

    @pytest.mark.asyncio
    async def test_analyze_impact_missing_resource(self, engine):
        """Impact analysis for missing resource returns error."""
        result = await engine.analyze_resource_impact("products", "missing")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_impact_level_delete_critical(self, engine):
        """Delete operation on critical relationship has high impact."""
        from src.revenium_mcp_server.relationships.graph import (
            RelationshipEdge,
            RelationshipStrength,
            RelationshipType,
            ResourceNode,
        )
        edge = RelationshipEdge(
            ResourceNode("a", "1"),
            ResourceNode("b", "2"),
            RelationshipType.BELONGS_TO,
            strength=RelationshipStrength.CRITICAL,
        )
        level = engine._assess_impact_level(edge, "delete")
        assert level == "high"

    @pytest.mark.asyncio
    async def test_impact_level_update_critical(self, engine):
        """Update operation on critical relationship has medium impact."""
        from src.revenium_mcp_server.relationships.graph import (
            RelationshipEdge,
            RelationshipStrength,
            RelationshipType,
            ResourceNode,
        )
        edge = RelationshipEdge(
            ResourceNode("a", "1"),
            ResourceNode("b", "2"),
            RelationshipType.BELONGS_TO,
            strength=RelationshipStrength.CRITICAL,
        )
        assert engine._assess_impact_level(edge, "update") == "medium"

    @pytest.mark.asyncio
    async def test_impact_level_unknown_operation(self, engine):
        """Unknown operation type returns low impact."""
        from src.revenium_mcp_server.relationships.graph import (
            RelationshipEdge,
            RelationshipStrength,
            RelationshipType,
            ResourceNode,
        )
        edge = RelationshipEdge(
            ResourceNode("a", "1"),
            ResourceNode("b", "2"),
            RelationshipType.OWNS,
            strength=RelationshipStrength.STRONG,
        )
        assert engine._assess_impact_level(edge, "archive") == "low"

    @pytest.mark.asyncio
    async def test_impact_level_delete_strong(self, engine):
        """Delete on strong relationship is medium impact."""
        from src.revenium_mcp_server.relationships.graph import (
            RelationshipEdge,
            RelationshipStrength,
            RelationshipType,
            ResourceNode,
        )
        edge = RelationshipEdge(
            ResourceNode("a", "1"),
            ResourceNode("b", "2"),
            RelationshipType.OWNS,
            strength=RelationshipStrength.STRONG,
        )
        assert engine._assess_impact_level(edge, "delete") == "medium"

    @pytest.mark.asyncio
    async def test_impact_level_delete_weak(self, engine):
        """Delete on weak relationship is low impact."""
        from src.revenium_mcp_server.relationships.graph import (
            RelationshipEdge,
            RelationshipStrength,
            RelationshipType,
            ResourceNode,
        )
        edge = RelationshipEdge(
            ResourceNode("a", "1"),
            ResourceNode("b", "2"),
            RelationshipType.REFERENCES,
            strength=RelationshipStrength.WEAK,
        )
        assert engine._assess_impact_level(edge, "delete") == "low"


class TestNavigationPath:
    """Test navigation path finding between resources."""

    @pytest.mark.asyncio
    async def test_find_path_between_connected_resources(self, engine):
        """Path is found between connected resources."""
        await engine.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = await engine.get_navigation_path("products", "p1", "organizations", "org1")
        assert result["success"] is True
        assert result["path_found"] is True
        assert result["path_length"] > 0

    @pytest.mark.asyncio
    async def test_no_path_between_disconnected_resources(self, engine):
        """No path found between disconnected resources."""
        await engine.add_resource("products", {"id": "p1"})
        await engine.add_resource("alerts", {"id": "a1"})
        result = await engine.get_navigation_path("products", "p1", "alerts", "a1")
        assert result["success"] is True
        assert result["path_found"] is False

    @pytest.mark.asyncio
    async def test_path_missing_source(self, engine):
        """Error when source resource doesn't exist."""
        result = await engine.get_navigation_path("products", "missing", "orgs", "o1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_path_missing_target(self, engine):
        """Error when target resource doesn't exist."""
        await engine.add_resource("products", {"id": "p1"})
        result = await engine.get_navigation_path("products", "p1", "orgs", "missing")
        assert result["success"] is False
