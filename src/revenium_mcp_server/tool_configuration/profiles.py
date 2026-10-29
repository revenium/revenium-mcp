"""Tool Profile Definitions

Defines the tool sets for each profile tier optimized for AI analytics and usage-based billing.

Profile Structure:
- Starter (12 tools): Essential cost monitoring and alerting
- Business (37 tools): Complete AI analytics and usage-based billing capabilities (default)

A domain that both reads and changes data is published as a read-only tool and a
write tool (see ``common/tool_surface.py``); a profile lists both names, and
leaving the write name out of a custom configuration publishes the domain read-only.
"""

from typing import Dict, Set


PROFILE_DEFINITIONS: Dict[str, Set[str]] = {
    "starter": {
        "get_business_analytics",
        "get_alerts",
        "manage_alerts",
        "get_slack",
        "manage_slack",
        "get_metering",
        "manage_metering",
        "get_system_setup",
        "manage_system_setup",
        "system_diagnostics",
        "manage_system_settings",
        "tool_introspection",
    },
    "business": {
        # Starter tools (12)
        "get_business_analytics",
        "get_alerts",
        "manage_alerts",
        "get_slack",
        "manage_slack",
        "get_metering",
        "manage_metering",
        "get_system_setup",
        "manage_system_setup",
        "system_diagnostics",
        "manage_system_settings",
        "tool_introspection",
        # Additional business tools (25)
        "get_sources",
        "manage_sources",
        "get_workflows",
        "manage_workflows",
        "get_credentials",
        "manage_credentials",
        "get_products",
        "manage_products",
        "get_customers",
        "manage_customers",
        "get_subscriptions",
        "manage_subscriptions",
        "get_usage_meters",
        "manage_usage_meters",
        "get_capabilities",
        "get_jobs",
        "manage_jobs",
        "get_tools",
        "manage_tools",
        "get_agents",
        "manage_agents",
        "get_ai_insights",
        "manage_ai_insights",
        "get_cost_controls",
        "manage_cost_controls",
    },
}

# Profile tool counts for validation
PROFILE_TOOL_COUNTS = {"starter": 12, "business": 37}


def validate_profile_definitions() -> bool:
    """Validate profile definitions meet PRD requirements.

    Returns:
        bool: True if all profiles are valid
    """
    for profile_name, expected_count in PROFILE_TOOL_COUNTS.items():
        actual_count = len(PROFILE_DEFINITIONS[profile_name])
        if actual_count != expected_count:
            return False
    return True


def get_profile_tools(profile_name: str) -> Set[str]:
    """Get tool set for a specific profile.

    Args:
        profile_name: Name of the profile (starter/business)

    Returns:
        Set of tool names for the profile

    Raises:
        ValueError: If profile name is invalid
    """
    if profile_name not in PROFILE_DEFINITIONS:
        valid_profiles = list(PROFILE_DEFINITIONS.keys())
        raise ValueError(f"Invalid profile '{profile_name}'. Valid profiles: {valid_profiles}")

    return PROFILE_DEFINITIONS[profile_name].copy()


def is_tool_in_profile(tool_name: str, profile_name: str) -> bool:
    """Check if a tool is included in a specific profile.

    Args:
        tool_name: Name of the tool to check
        profile_name: Name of the profile

    Returns:
        bool: True if tool is in profile
    """
    if profile_name not in PROFILE_DEFINITIONS:
        return False

    return tool_name in PROFILE_DEFINITIONS[profile_name]
