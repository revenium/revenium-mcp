#!/usr/bin/env python3
"""
Slack Configuration Formatting Utilities

This module contains formatting functions for Slack configuration responses,
separated to maintain compliance with the 300-line module limit.
"""

from typing import Any, Dict, List

from mcp.types import TextContent

from ..config_store import get_config_value


def format_configurations_list(response: Dict[str, Any], page: int) -> List[TextContent]:
    """Format configurations list response."""
    configurations = response.get("content", [])
    total_elements = response.get("totalElements", 0)
    total_pages = response.get("totalPages", 0)

    if not configurations:
        return [
            TextContent(
                type="text",
                text="# No Slack Configurations Found\n\n"
                "No Slack configurations are currently set up.\n\n"
                "**To add a configuration:**\n"
                "Use `slack_management(action='initiate_oauth')` to start setup.",
            )
        ]

    result_text = f"# Slack Configurations ({total_elements} total)\n\n"

    if total_pages > 1:
        result_text += f"**Page {page + 1} of {total_pages}** (showing {len(configurations)} configurations)\n\n"

    for i, config in enumerate(configurations, 1):
        result_text += format_single_config_summary(config, i)

    result_text += format_pagination_info(page, total_pages)
    result_text += format_usage_instructions()

    return [TextContent(type="text", text=result_text)]


def format_single_config_summary(config: Dict[str, Any], index: int) -> str:
    """Format a single configuration summary."""
    config_id = config.get("id", "Unknown")
    name = config.get("name", "Unnamed Configuration")
    # Use correct API field names from the actual response
    channel_name = config.get("channelName", "N/A")
    team_name = config.get("teamName") or config.get("team", {}).get("label", "Unknown Workspace")
    created_date = config.get("created", "Unknown")

    return (
        f"## {index}. {name}\n"
        f"- **ID:** `{config_id}`\n"
        f"- **Workspace:** {team_name}\n"
        f"- **Channel:** {channel_name}\n"
        f"- **Created:** {created_date}\n\n"
    )


def format_pagination_info(page: int, total_pages: int) -> str:
    """Format pagination information."""
    if total_pages <= 1:
        return ""

    result = "---\n\n**Navigation:**\n"
    if page > 0:
        result += f"- Previous page: `slack_management(action='list_configurations', page={page-1})`\n"
    if page < total_pages - 1:
        result += f"- Next page: `slack_management(action='list_configurations', page={page+1})`\n"

    return result


def format_usage_instructions() -> str:
    """Format usage instructions."""
    return (
        "\n**Usage:**\n"
        "- View details: `slack_management(action='get_configuration', config_id='CONFIG_ID')`\n"
        "- Set as default: `slack_management(action='set_default_configuration', config_id='CONFIG_ID')`\n"
    )


def format_configuration_details(config: Dict[str, Any], config_id: str) -> List[TextContent]:
    """Format configuration details response."""
    name = config.get("name", "Unnamed Configuration")
    # Use correct API field names from the actual response
    team_name = config.get("teamName") or config.get("team", {}).get("label", "Unknown Workspace")
    channel_name = config.get("channelName", "N/A")
    created_date = config.get("created", "Unknown")
    updated_date = config.get("updated", "Unknown")

    result_text = f"# Slack Configuration: {name}\n\n"
    result_text += f"**Configuration ID:** `{config_id}`\n\n"
    result_text += "**Details:**\n"
    result_text += f"- **Workspace:** {team_name}\n"
    result_text += f"- **Channel:** {channel_name}\n"
    result_text += f"- **Created:** {created_date}\n"
    result_text += f"- **Updated:** {updated_date}\n\n"

    # Check if this is the current default
    current_default = get_config_value("REVENIUM_DEFAULT_SLACK_CONFIG_ID")
    if current_default == config_id:
        result_text += "**This is your current default Slack configuration.**\n\n"

    result_text += "**Actions:**\n"
    result_text += f"- Set as default: `slack_management(action='set_default_configuration', config_id='{config_id}')`\n"
    result_text += (
        "- Back to list: `slack_management(action='list_configurations')`\n"
    )

    return [TextContent(type="text", text=result_text)]


def format_default_set_success(config: Dict[str, Any], config_id: str) -> List[TextContent]:
    """Format successful default configuration set response."""
    name = config.get("name", "Unnamed Configuration")
    # Use correct API field names from the actual response
    team_name = config.get("teamName") or config.get("team", {}).get("label", "Unknown Workspace")
    channel_name = config.get("channelName", "N/A")

    result_text = "# Default Slack Configuration Set\n\n"
    result_text += f"**Configuration:** {name}\n"
    result_text += f"**Workspace:** {team_name}\n"
    result_text += f"**Channel:** {channel_name}\n"
    result_text += f"**ID:** `{config_id}`\n\n"
    result_text += "This configuration will now be used as the default for new alerts.\n\n"
    result_text += "**Note:** To make persistent, add to your .env file:\n"
    result_text += f'```bash\nREVENIUM_DEFAULT_SLACK_CONFIG_ID="{config_id}"\n```\n'

    return [TextContent(type="text", text=result_text)]


def format_no_default_message() -> List[TextContent]:
    """Format no default configuration message."""
    result_text = "# No Default Slack Configuration\n\n"
    result_text += "No default Slack configuration is currently set.\n\n"
    result_text += "**To set a default:**\n"
    result_text += (
        "1. List configurations: `slack_management(action='list_configurations')`\n"
    )
    result_text += "2. Set default: `slack_management(action='set_default_configuration', config_id='CONFIG_ID')`\n"

    return [TextContent(type="text", text=result_text)]


def format_default_configuration(config: Dict[str, Any], config_id: str) -> List[TextContent]:
    """Format default configuration details."""
    name = config.get("name", "Unnamed Configuration")
    # Use correct API field names from the actual response
    team_name = config.get("teamName") or config.get("team", {}).get("label", "Unknown Workspace")
    channel_name = config.get("channelName", "N/A")

    result_text = "# Current Default Slack Configuration\n\n"
    result_text += f"**Configuration:** {name}\n"
    result_text += f"**Workspace:** {team_name}\n"
    result_text += f"**Channel:** {channel_name}\n"
    result_text += f"**ID:** `{config_id}`\n\n"
    result_text += "This configuration will be automatically used for new alerts.\n"

    return [TextContent(type="text", text=result_text)]


def format_oauth_url_response(oauth_url: str, app_base_url: str) -> List[TextContent]:
    """Format OAuth URL response."""
    result_text = "# Slack OAuth Setup URL\n\n"
    result_text += f"**[Open Slack Setup]({oauth_url})**\n\n"
    result_text += f"```\n{oauth_url}\n```\n\n"
    result_text += "**Steps:**\n"
    result_text += "1. Click the link above or copy the URL to your browser\n"
    result_text += "2. Complete the Slack OAuth authorization\n"
    result_text += (
        "3. Return and refresh: `slack_management(action='list_configurations')`\n"
    )

    return [TextContent(type="text", text=result_text)]


def get_examples_text() -> str:
    """Get examples text for Slack configuration management."""
    return """# Slack Configuration Management Examples

## Basic Operations
```python
# List all configurations
slack_management(action="list_configurations")

# Get specific configuration
slack_management(action="get_configuration", config_id="slack-123")

# Set default configuration
slack_management(action="set_default_configuration", config_id="slack-123")

# Get current default
slack_management(action="get_default_configuration")

# Get OAuth setup URL
slack_management(action="get_app_oauth_url")
```

## Advanced Usage
```python
# Pagination
slack_management(action="list_configurations", page=1, size=10)

# Dry-run mode (validation only)
slack_management(action="set_default_configuration", config_id="slack-123", dry_run=true)
```

## Common Workflows
### Setup New Slack Integration
1. Get OAuth URL: `slack_management(action="get_app_oauth_url")`
2. Complete OAuth in browser
3. List configurations: `slack_management(action="list_configurations")`
4. Set default: `slack_management(action="set_default_configuration", config_id="new-config-id")`
"""


def get_capabilities_text() -> str:
    """Get capabilities text for Slack configuration management."""
    return """# Slack Configuration Management Capabilities

## Tool Overview
Comprehensive management of Slack configurations for alert notifications with full CRUD operations and default configuration management.

## Available Actions
- **list_configurations**: List all Slack configurations with pagination
- **get_configuration**: Get detailed information about a specific configuration
- **set_default_configuration**: Set a configuration as default for new alerts
- **get_default_configuration**: Get current default configuration details
- **get_app_oauth_url**: Get OAuth URL for setting up new Slack integrations
- **get_examples**: Get working examples and usage patterns
- **get_capabilities**: Get this comprehensive capabilities documentation

## Parameters
- **action** (string, required): Action to perform
- **config_id** (string): Configuration ID (required for get/set operations)
- **page** (integer): Page number for pagination (default: 0)
- **size** (integer): Items per page (default: 20, max: 100)
- **dry_run** (boolean): Validation-only mode (default: false)

## Integration Points
- **Alert Management**: Default configurations automatically used in alert creation
- **OAuth Workflow**: Integrates with slack_management for setup
- **Configuration Store**: Persists default settings via environment variables

## Error Handling
- Structured error responses with actionable suggestions
- Validation of all parameters before execution
- Graceful handling of API connectivity issues
"""
