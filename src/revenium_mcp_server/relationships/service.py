"""Resource Relationship Service.

This module provides a service interface for resource relationship discovery
that can be integrated into the MCP server.
"""

from typing import Any, Dict, List, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from .engine import relationship_engine


class ResourceRelationshipService:
    """Service for providing resource relationship capabilities via MCP."""

    def __init__(self):
        """Initialize the relationship service."""
        self.engine = relationship_engine

    async def handle_relationship_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle resource relationship actions.

        Args:
            action: Relationship action to perform
            arguments: Action arguments

        Returns:
            Formatted response
        """
        try:
            if action == "get_resource_relationships":
                return await self._handle_get_resource_relationships(arguments)
            elif action == "find_related_resources":
                return await self._handle_find_related_resources(arguments)
            elif action == "validate_cross_resource_operation":
                return await self._handle_validate_cross_resource_operation(arguments)
            elif action == "get_dependency_graph":
                return await self._handle_get_dependency_graph()
            elif action == "get_relationship_patterns":
                return await self._handle_get_relationship_patterns()
            elif action == "analyze_resource_impact":
                return await self._handle_analyze_resource_impact(arguments)
            elif action == "get_navigation_path":
                return await self._handle_get_navigation_path(arguments)
            elif action == "add_resource":
                return await self._handle_add_resource(arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()
            else:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ **Error**: Unknown relationship action '{action}'\n\n"
                        f"**Supported actions**: get_resource_relationships, find_related_resources, "
                        f"validate_cross_resource_operation, get_dependency_graph, get_relationship_patterns, "
                        f"analyze_resource_impact, get_navigation_path, add_resource, get_capabilities, get_examples",
                    )
                ]

        except Exception as e:
            logger.error(f"Error in resource relationship action {action}: {e}")
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Relationship Error**: {str(e)}\n\n"
                    f"Please check your request parameters and try again.",
                )
            ]

    async def _handle_get_resource_relationships(
        self, arguments: Dict[str, Any]
    ) -> List[TextContent]:
        """Handle getting relationships for a specific resource."""
        resource_type = arguments.get("resource_type")
        resource_id = arguments.get("resource_id")

        if not resource_type or not resource_id:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: resource_type and resource_id parameters are required",
                )
            ]

        result = await self.engine.get_resource_relationships(resource_type, resource_id)

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        relationships = result["relationships"]

        text = f"🔗 **Resource Relationships: {resource_type}:{resource_id}**\n\n"

        if "resource" in relationships:
            resource = relationships["resource"]
            text += (
                f"**Resource**: {resource.get('name', 'N/A')} ({resource.get('status', 'N/A')})\n\n"
            )

        # Outgoing relationships
        outgoing = relationships.get("outgoing_relationships", [])
        if outgoing:
            text += "**Outgoing Relationships** (this resource → others):\n"
            for rel in outgoing:
                target = rel["target"]
                text += f"• **{rel['relationship_type']}** → {target['resource_type']}:{target['resource_id']}"
                if target.get("name"):
                    text += f" ({target['name']})"
                text += f" [{rel['strength']}]\n"
            text += "\n"

        # Incoming relationships
        incoming = relationships.get("incoming_relationships", [])
        if incoming:
            text += "**Incoming Relationships** (others → this resource):\n"
            for rel in incoming:
                source = rel["source"]
                text += f"• {source['resource_type']}:{source['resource_id']}"
                if source.get("name"):
                    text += f" ({source['name']})"
                text += f" **{rel['relationship_type']}** → this resource [{rel['strength']}]\n"
            text += "\n"

        # Related resources summary
        related = relationships.get("related_resources", {})
        if any(related.values()):
            text += "**Related Resources Summary**:\n"
            for rel_type, resources in related.items():
                if resources:
                    text += f"• **{rel_type.replace('_', ' ').title()}**: {len(resources)} resource(s)\n"

        return [TextContent(type="text", text=text)]

    async def _handle_find_related_resources(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle finding related resources."""
        resource_type = arguments.get("resource_type")
        resource_id = arguments.get("resource_id")
        relationship_types = arguments.get("relationship_types")
        max_depth = arguments.get("max_depth", 2)

        if not resource_type or not resource_id:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: resource_type and resource_id parameters are required",
                )
            ]

        result = await self.engine.find_related_resources(
            resource_type, resource_id, relationship_types, max_depth
        )

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        related = result["related_resources"]

        text = f"🔍 **Related Resources: {resource_type}:{resource_id}**\n\n"
        text += f"**Search Depth**: {max_depth}\n"

        if relationship_types:
            text += f"**Filtered by**: {', '.join(relationship_types)}\n"

        text += "\n"

        # Show related graph statistics
        graph = related.get("related_graph", {})
        if graph:
            text += f"**Found**: {graph.get('node_count', 0)} related resources, "
            text += f"{graph.get('edge_count', 0)} relationships\n\n"

            # Show nodes by type
            nodes = graph.get("nodes", [])
            if nodes:
                node_types = {}
                for node in nodes:
                    node_type = node["resource_type"]
                    node_types[node_type] = node_types.get(node_type, 0) + 1

                text += "**Resource Types Found**:\n"
                for node_type, count in sorted(node_types.items()):
                    text += f"• {node_type}: {count} resource(s)\n"

        return [TextContent(type="text", text=text)]

    async def _handle_validate_cross_resource_operation(
        self, arguments: Dict[str, Any]
    ) -> List[TextContent]:
        """Handle validating cross-resource operations."""
        operation = arguments.get("operation")

        if not operation:
            return [TextContent(type="text", text="❌ **Error**: operation parameter is required")]

        result = await self.engine.validate_cross_resource_operation(operation)

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        validation = result["validation_result"]

        text = "✅ **Cross-Resource Operation Validation**\n\n"

        if validation.get("validation_passed"):
            text += "✅ **Status**: Validation PASSED\n"
        else:
            text += "❌ **Status**: Validation FAILED\n"

        text += f"**Errors**: {validation.get('error_count', 0)}\n"
        text += f"**Warnings**: {validation.get('warning_count', 0)}\n\n"

        # Show errors
        errors = validation.get("errors", [])
        if errors:
            text += "**Validation Errors**:\n"
            for error in errors:
                text += f"• **{error.get('rule_name', 'Unknown')}**: {error.get('message', 'No message')}\n"
            text += "\n"

        # Show warnings
        warnings = validation.get("warnings", [])
        if warnings:
            text += "**Validation Warnings**:\n"
            for warning in warnings:
                text += f"• **{warning.get('rule_name', 'Unknown')}**: {warning.get('message', 'No message')}\n"
            text += "\n"

        # Show recommendations
        recommendations = validation.get("recommendations", [])
        if recommendations:
            text += "**Recommendations**:\n"
            for rec in recommendations:
                text += f"• {rec}\n"

        return [TextContent(type="text", text=text)]

    async def _handle_get_dependency_graph(self) -> List[TextContent]:
        """Handle getting the dependency graph."""
        result = await self.engine.get_dependency_graph()

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        statistics = result.get("statistics", {})

        text = "📊 **Resource Dependency Graph**\n\n"
        text += f"**Total Resources**: {statistics.get('total_nodes', 0)}\n"
        text += f"**Total Relationships**: {statistics.get('total_edges', 0)}\n"
        text += f"**Average Connections**: {statistics.get('average_degree', 0):.1f}\n\n"

        # Resource types
        resource_types = statistics.get("resource_types", {})
        if resource_types:
            text += "**Resource Types**:\n"
            for res_type, count in sorted(resource_types.items()):
                text += f"• {res_type}: {count} resource(s)\n"
            text += "\n"

        # Relationship types
        relationship_types = statistics.get("relationship_types", {})
        if relationship_types:
            text += "**Relationship Types**:\n"
            for rel_type, count in sorted(relationship_types.items()):
                text += f"• {rel_type}: {count} relationship(s)\n"

        return [TextContent(type="text", text=text)]

    async def _handle_get_relationship_patterns(self) -> List[TextContent]:
        """Handle getting relationship patterns."""
        result = await self.engine.get_relationship_patterns()

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        patterns = result.get("patterns", {})

        text = "🔗 **Resource Relationship Patterns**\n\n"
        text += f"**Total Patterns**: {result.get('total_patterns', 0)}\n\n"

        for resource_type, pattern in sorted(patterns.items()):
            text += f"**{resource_type.title()}**:\n"

            supported_rels = pattern.get("supported_relationships", [])
            if supported_rels:
                text += f"  Relationships: {', '.join(supported_rels)}\n"

            field_mappings = pattern.get("field_mappings", {})
            if field_mappings:
                text += "  Field Mappings:\n"
                for field, mapping in field_mappings.items():
                    text += f"    • {field} → {mapping['target_type']} ({mapping['relationship_type']})\n"

            text += "\n"

        return [TextContent(type="text", text=text)]

    async def _handle_analyze_resource_impact(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle analyzing resource impact."""
        resource_type = arguments.get("resource_type")
        resource_id = arguments.get("resource_id")
        operation = arguments.get("operation", "delete")

        if not resource_type or not resource_id:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: resource_type and resource_id parameters are required",
                )
            ]

        result = await self.engine.analyze_resource_impact(resource_type, resource_id, operation)

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        impact = result["impact_analysis"]

        text = f"⚠️ **Resource Impact Analysis: {operation.upper()}**\n\n"
        text += f"**Resource**: {resource_type}:{resource_id}\n"
        text += f"**Operation**: {operation}\n"
        text += f"**Total Affected**: {impact.get('total_affected_resources', 0)} resource(s)\n"
        text += f"**High Impact**: {impact.get('high_impact_count', 0)} resource(s)\n\n"

        # Dependent resources
        dependent = impact.get("dependent_resources", [])
        if dependent:
            text += "**Resources That Depend On This** (will be affected):\n"
            for dep in dependent:
                res = dep["resource"]
                text += f"• {res['resource_type']}:{res['resource_id']}"
                if res.get("name"):
                    text += f" ({res['name']})"
                text += f" - {dep['relationship_type']} [{dep['impact_level']} impact]\n"
            text += "\n"

        # Dependencies
        dependencies = impact.get("dependency_resources", [])
        if dependencies:
            text += "**Resources This Depends On** (may need cleanup):\n"
            for dep in dependencies:
                res = dep["resource"]
                text += f"• {res['resource_type']}:{res['resource_id']}"
                if res.get("name"):
                    text += f" ({res['name']})"
                text += f" - {dep['relationship_type']} [{dep['impact_level']} impact]\n"

        return [TextContent(type="text", text=text)]

    async def _handle_get_navigation_path(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle getting navigation path between resources."""
        from_resource_type = arguments.get("from_resource_type")
        from_resource_id = arguments.get("from_resource_id")
        to_resource_type = arguments.get("to_resource_type")
        to_resource_id = arguments.get("to_resource_id")

        if not all([from_resource_type, from_resource_id, to_resource_type, to_resource_id]):
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: from_resource_type, from_resource_id, to_resource_type, and to_resource_id parameters are required",
                )
            ]

        result = await self.engine.get_navigation_path(
            from_resource_type, from_resource_id, to_resource_type, to_resource_id
        )

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        text = "🗺️ **Navigation Path**\n\n"
        text += f"**From**: {from_resource_type}:{from_resource_id}\n"
        text += f"**To**: {to_resource_type}:{to_resource_id}\n\n"

        if not result.get("path_found"):
            text += "❌ **No path found** between these resources.\n"
            text += result.get("message", "")
        else:
            path = result.get("navigation_path", [])
            text += f"✅ **Path found** ({result.get('path_length', 0)} steps):\n\n"

            for step in path:
                from_res = step["from"]
                to_res = step["to"]
                text += f"**Step {step['step']}**: "
                text += f"{from_res['resource_type']}:{from_res['resource_id']}"
                if from_res.get("name"):
                    text += f" ({from_res['name']})"
                text += f" **{step['relationship']}** → "
                text += f"{to_res['resource_type']}:{to_res['resource_id']}"
                if to_res.get("name"):
                    text += f" ({to_res['name']})"
                text += f" [{step['strength']}]\n"

        return [TextContent(type="text", text=text)]

    async def _handle_add_resource(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle adding a resource to the relationship graph."""
        resource_type = arguments.get("resource_type")
        resource_data = arguments.get("resource_data")

        if not resource_type or not resource_data:
            return [
                TextContent(
                    type="text",
                    text="❌ **Error**: resource_type and resource_data parameters are required",
                )
            ]

        result = await self.engine.add_resource(resource_type, resource_data)

        if not result.get("success"):
            return [
                TextContent(
                    type="text", text=f"❌ **Error**: {result.get('error', 'Unknown error')}"
                )
            ]

        text = "✅ **Resource Added Successfully**\n\n"
        text += f"**Type**: {result['resource_type']}\n"
        text += f"**ID**: {result['resource_id']}\n"
        text += f"**Message**: {result['message']}\n\n"

        # Show discovered relationships
        relationships = result.get("relationships", {})
        outgoing = relationships.get("outgoing_relationships", [])
        if outgoing:
            text += f"**Discovered {len(outgoing)} relationship(s)**:\n"
            for rel in outgoing[:5]:  # Show first 5
                target = rel["target"]
                text += f"• {rel['relationship_type']} → {target['resource_type']}:{target['resource_id']}\n"
            if len(outgoing) > 5:
                text += f"• ... and {len(outgoing) - 5} more\n"

        return [TextContent(type="text", text=text)]

    async def _handle_get_capabilities(self) -> List[TextContent]:
        """Handle getting relationship service capabilities."""
        text = """🔗 **Resource Relationship Service Capabilities**

## **What This Service Does**
Provides comprehensive resource relationship discovery, mapping, and analysis for the Revenium platform, enabling agents to understand how different resources relate to each other.

## **Available Actions**
• **get_resource_relationships**: Get all relationships for a specific resource
• **find_related_resources**: Find resources related to a given resource with filtering
• **validate_cross_resource_operation**: Validate operations that affect multiple resources
• **get_dependency_graph**: View the complete resource dependency graph
• **get_relationship_patterns**: See available relationship patterns and mappings
• **analyze_resource_impact**: Analyze the impact of operations on related resources
• **get_navigation_path**: Find navigation paths between two resources
• **add_resource**: Add a resource and discover its relationships

## **Key Features**
• Automatic relationship discovery from resource data
• Cross-resource validation and integrity checking
• Impact analysis for operations affecting multiple resources
• Navigation path finding between related resources
• Comprehensive dependency graph visualization
• Business rule validation for resource operations

## **Supported Resource Types**
• Products, Subscriptions, Sources, Users, Organizations, Teams, Alerts

## **Relationship Types**
• owns, belongs_to, references, depends_on, creates, monitors, configures, subscribes_to, manages, contains"""

        return [TextContent(type="text", text=text)]

    async def _handle_get_examples(self) -> List[TextContent]:
        """Handle getting relationship service examples."""
        text = """📋 **Resource Relationship Examples**

## **Basic Relationship Discovery**
```
get_resource_relationships(resource_type="products", resource_id="prod_123")
# Returns: All relationships for product prod_123

find_related_resources(resource_type="products", resource_id="prod_123", max_depth=2)
# Returns: All resources related to product within 2 relationship hops
```

## **Cross-Resource Validation**
```
validate_cross_resource_operation(operation={
    "type": "create",
    "resource_type": "subscriptions",
    "resource_data": {"product_id": "prod_123", "user_id": "user_456"}
})
# Returns: Validation result with errors/warnings
```

## **Impact Analysis**
```
analyze_resource_impact(resource_type="products", resource_id="prod_123", operation="delete")
# Returns: Analysis of what resources would be affected by deleting the product
```

## **Navigation and Discovery**
```
get_navigation_path(
    from_resource_type="users", from_resource_id="user_123",
    to_resource_type="alerts", to_resource_id="alert_456"
)
# Returns: Step-by-step path from user to alert through relationships

get_dependency_graph()
# Returns: Complete graph statistics and relationship overview
```

## **Resource Management**
```
add_resource(resource_type="products", resource_data={
    "id": "prod_789",
    "name": "New Product",
    "organization_id": "org_123",
    "source_ids": ["src_456", "src_789"]
})
# Returns: Added resource with discovered relationships
```"""

        return [TextContent(type="text", text=text)]


# Global service instance
resource_relationship_service = ResourceRelationshipService()
