"""Naming Convention Audit and Standardization Report.

This module provides tools to audit current naming conventions across all MCP tools
and generate standardization recommendations.
"""

from typing import Any, Dict, List

from loguru import logger

from .naming_standards import naming_standards


class NamingAudit:
    """Comprehensive audit of naming conventions across MCP tools."""

    def __init__(self):
        self.audit_results: Dict[str, Any] = {}
        self.standardization_plan: Dict[str, Any] = {}

    def audit_all_tools(self) -> Dict[str, Any]:
        """Perform comprehensive audit of all MCP tools."""
        logger.info("Starting comprehensive naming convention audit")

        # Define current tool signatures based on enhanced_server.py
        tool_signatures = {
            "manage_products": {
                "action": "str",
                "product_id": "Optional[str]",
                "product_data": "Optional[dict]",
                "page": "int",
                "size": "int",
                "filters": "Optional[dict]",
            },
            "manage_subscriptions": {
                "action": "str",
                "subscription_id": "Optional[str]",
                "subscription_data": "Optional[dict]",
                "page": "int",
                "size": "int",
                "filters": "Optional[dict]",
            },
            "manage_sources": {
                "action": "str",
                "source_id": "Optional[str]",
                "source_data": "Optional[dict]",
                "page": "int",
                "size": "int",
                "filters": "Optional[dict]",
            },
            "manage_customers": {
                "action": "str",
                "resource_type": "str",
                "user_id": "Optional[str]",
                "subscriber_id": "Optional[str]",
                "organization_id": "Optional[str]",
                "team_id": "Optional[str]",
                "email": "Optional[str]",
                "user_data": "Optional[dict]",
                "subscriber_data": "Optional[dict]",
                "organization_data": "Optional[dict]",
                "team_data": "Optional[dict]",
                "page": "int",
                "size": "int",
                "filters": "Optional[dict]",
            },
            "manage_alerts": {
                "action": "str",
                "resource_type": "str",
                "anomaly_id": "Optional[str]",
                "alert_id": "Optional[str]",
                "anomaly_data": "Optional[dict]",
                "page": "int",
                "size": "int",
                "filters": "Optional[dict]",
                "query": "Optional[str]",
            },
            "manage_workflows": {
                "action": "str",
                "workflow_id": "Optional[str]",
                "context": "Optional[dict]",
                "step_result": "Optional[dict]",
            },
        }

        audit_results = {}

        for tool_name, parameters in tool_signatures.items():
            tool_audit = self._audit_tool_parameters(tool_name, parameters)
            audit_results[tool_name] = tool_audit

        # Generate overall compliance metrics
        overall_metrics = self._calculate_overall_metrics(audit_results)

        self.audit_results = {
            "tools": audit_results,
            "overall_metrics": overall_metrics,
            "standardization_recommendations": self._generate_standardization_recommendations(
                audit_results
            ),
        }

        return self.audit_results

    def _audit_tool_parameters(self, tool_name: str, parameters: Dict[str, str]) -> Dict[str, Any]:
        """Audit parameters for a specific tool."""
        violations = []
        compliant_params = []

        for param_name, param_type in parameters.items():
            is_compliant = naming_standards.validate_parameter_name(param_name)

            if is_compliant:
                compliant_params.append(param_name)
            else:
                violation = {
                    "parameter": param_name,
                    "type": param_type,
                    "issue": "Non-snake_case naming",
                    "suggestion": naming_standards.convert_to_snake_case(param_name),
                }
                violations.append(violation)

        # Check for standard patterns
        id_fields = [p for p in parameters.keys() if p.endswith("_id")]
        data_fields = [p for p in parameters.keys() if p.endswith("_data")]

        return {
            "total_parameters": len(parameters),
            "compliant_parameters": len(compliant_params),
            "violations": violations,
            "compliance_percentage": (len(compliant_params) / len(parameters)) * 100,
            "id_fields": id_fields,
            "data_fields": data_fields,
            "follows_standard_patterns": {
                "id_fields": len(id_fields) > 0,
                "data_fields": len(data_fields) > 0,
                "has_action": "action" in parameters,
                "has_pagination": "page" in parameters and "size" in parameters,
            },
        }

    def _calculate_overall_metrics(self, audit_results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate overall compliance metrics across all tools."""
        total_params = sum(tool["total_parameters"] for tool in audit_results.values())
        total_compliant = sum(tool["compliant_parameters"] for tool in audit_results.values())
        total_violations = sum(len(tool["violations"]) for tool in audit_results.values())

        # Pattern compliance
        tools_with_standard_patterns = sum(
            1 for tool in audit_results.values() if all(tool["follows_standard_patterns"].values())
        )

        return {
            "total_parameters": total_params,
            "total_compliant": total_compliant,
            "total_violations": total_violations,
            "overall_compliance_percentage": (
                (total_compliant / total_params) * 100 if total_params > 0 else 0
            ),
            "tools_with_standard_patterns": tools_with_standard_patterns,
            "total_tools": len(audit_results),
            "pattern_compliance_percentage": (tools_with_standard_patterns / len(audit_results))
            * 100,
        }

    def _generate_standardization_recommendations(
        self, audit_results: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate actionable standardization recommendations."""
        recommendations = []

        # Check for violations
        for tool_name, tool_audit in audit_results.items():
            if tool_audit["violations"]:
                recommendations.append(
                    {
                        "type": "parameter_naming",
                        "tool": tool_name,
                        "priority": "medium",
                        "description": f"Fix {len(tool_audit['violations'])} parameter naming violations",
                        "violations": tool_audit["violations"],
                    }
                )

        # Check for missing standard patterns
        for tool_name, tool_audit in audit_results.items():
            patterns = tool_audit["follows_standard_patterns"]
            if not patterns["has_action"]:
                recommendations.append(
                    {
                        "type": "missing_action",
                        "tool": tool_name,
                        "priority": "high",
                        "description": "Missing standard 'action' parameter",
                    }
                )

        return recommendations

    def generate_compliance_report(self) -> str:
        """Generate a human-readable compliance report."""
        if not self.audit_results:
            self.audit_all_tools()

        metrics = self.audit_results["overall_metrics"]

        report = "# 📊 **MCP Tools Naming Convention Compliance Report**\n\n"

        # Overall metrics
        report += "## 🎯 **Overall Compliance**\n\n"
        report += f"• **Total Parameters**: {metrics['total_parameters']}\n"
        report += f"• **Compliant Parameters**: {metrics['total_compliant']}\n"
        report += f"• **Violations**: {metrics['total_violations']}\n"
        report += f"• **Overall Compliance**: {metrics['overall_compliance_percentage']:.1f}%\n\n"

        # Pattern compliance
        report += "## 🔧 **Pattern Compliance**\n\n"
        report += f"• **Tools Following Standard Patterns**: {metrics['tools_with_standard_patterns']}/{metrics['total_tools']}\n"
        report += f"• **Pattern Compliance**: {metrics['pattern_compliance_percentage']:.1f}%\n\n"

        # Tool-by-tool breakdown
        report += "## 📋 **Tool-by-Tool Analysis**\n\n"
        for tool_name, tool_audit in self.audit_results["tools"].items():
            report += f"### **{tool_name}**\n"
            report += f"• Compliance: {tool_audit['compliance_percentage']:.1f}% ({tool_audit['compliant_parameters']}/{tool_audit['total_parameters']})\n"

            if tool_audit["violations"]:
                report += f"• Violations: {len(tool_audit['violations'])}\n"
                for violation in tool_audit["violations"]:
                    report += f"  - `{violation['parameter']}` → `{violation['suggestion']}`\n"
            else:
                report += "• ✅ No violations found\n"
            report += "\n"

        # Recommendations
        if self.audit_results["standardization_recommendations"]:
            report += "## 💡 **Recommendations**\n\n"
            for i, rec in enumerate(self.audit_results["standardization_recommendations"], 1):
                report += (
                    f"{i}. **{rec['type']}** ({rec['priority']} priority): {rec['description']}\n"
                )

        return report


# Global audit instance
naming_audit = NamingAudit()


def run_naming_audit() -> str:
    """Run the naming audit and return the compliance report."""
    return naming_audit.generate_compliance_report()
