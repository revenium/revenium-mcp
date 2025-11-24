"""Tool Profile Definitions

Defines the tool sets for each profile tier optimized for AI analytics and usage-based billing.

Profile Structure:
- Starter (7 tools): Essential cost monitoring and alerting
- Business (15 tools): Complete AI analytics and usage-based billing capabilities (default)

Note: Enterprise profile removed as it was redundant after infrastructure monitoring tools removal.
"""

from typing import Dict, Set

# Profile tool definitions as specified in PRD section 6.2
PROFILE_DEFINITIONS: Dict[str, Set[str]] = {
    "starter": {
        "business_analytics_management",
        "manage_alerts",
        "slack_management",
        "manage_metering",
        "system_setup",
        "system_diagnostics",
        "tool_introspection",
    },
    "business": {
        # Starter tools (7)
        "business_analytics_management",
        "manage_alerts",
        "slack_management",
        "manage_metering",
        "system_setup",
        "system_diagnostics",
        "tool_introspection",
        # Additional business tools (8)
        "manage_sources",
        "manage_workflows",
        "manage_subscriber_credentials",
        "manage_products",
        "manage_customers",
        "manage_subscriptions",
        "manage_metering_elements",
        "manage_capabilities",
    },
}

# Profile tool counts for validation
PROFILE_TOOL_COUNTS = {"starter": 7, "business": 15}


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
