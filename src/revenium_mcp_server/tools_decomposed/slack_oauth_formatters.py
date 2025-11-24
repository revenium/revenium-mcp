#!/usr/bin/env python3
"""
Slack OAuth Workflow Formatting Utilities

This module contains formatting functions for Slack OAuth workflow responses,
separated to maintain compliance with the 300-line module limit.
"""

from typing import Any, Dict, List

from mcp.types import TextContent


def format_oauth_initiation_response(
    oauth_url: str, app_base_url: str, return_to: str
) -> List[TextContent]:
    """Format OAuth initiation response."""
    result_text = "# Slack OAuth Workflow Started\n\n"

    # Critical warning - must be prominently displayed
    result_text += "**ENSURE you are  logged into Revenium before clicking OAuth link**\n\n"
    result_text += "If you are not already logged into Revenium in your browser, please:\n"
    result_text += f"1. Open {app_base_url} in a new tab\n"
    result_text += "2. Log in to your Revenium account\n"
    result_text += "3. Then return here and click the OAuth link below\n\n"

    result_text += "**Click here to authorize Slack integration:**\n\n"
    result_text += f"**[Connect Slack to Revenium]({oauth_url})**\n\n"
    result_text += f"```\n{oauth_url}\n```\n\n"
    result_text += "## Next Steps\n\n"
    result_text += "1. **Ensure you are logged into Revenium** (see critical requirement above)\n"
    result_text += "2. **Click the link above** or copy the URL to your browser\n"
    result_text += "3. **Authorize Slack** and choose your workspace/channel\n"
    result_text += "4. **Return here** and check status: `slack_oauth_workflow(action='refresh_configurations')`\n\n"
    result_text += f"**Environment**: {app_base_url}\n"

    return [TextContent(type="text", text=result_text)]


def format_oauth_instructions() -> List[TextContent]:
    """Format detailed OAuth instructions and troubleshooting."""
    result_text = "# Slack OAuth Setup Instructions\n\n"

    result_text += "## Complete Setup Process\n\n"
    result_text += "### 1. Initiate OAuth\n"
    result_text += "```\nslack_oauth_workflow(action='initiate_oauth')\n```\n\n"

    result_text += "### 2. Browser Workflow\n"
    result_text += "- **Open the provided link** in your web browser\n"
    result_text += "- **Sign in** to your Revenium account\n"
    result_text += "- **Authorize Slack** when redirected to Slack\n"
    result_text += "- **Select workspace and channel** for notifications\n"
    result_text += "- **Confirm permissions** for the Revenium app\n"
    result_text += "- **Wait for success message** in the Revenium web app\n\n"

    result_text += "### 3. Return to MCP\n"
    result_text += "```\nslack_oauth_workflow(action='refresh_configurations')\n```\n\n"

    result_text += "## Troubleshooting\n\n"
    result_text += "### Common Issues\n\n"
    result_text += '**"Page not found" error:**\n'
    result_text += "- Check your `REVENIUM_APP_BASE_URL` setting\n"
    result_text += "- Ensure the Revenium web application is running\n"
    result_text += "- Verify you're using the correct environment (dev/prod)\n\n"

    result_text += '**"Authentication failed" error:**\n'
    result_text += "- Ensure you're logged into the correct Revenium account\n"
    result_text += "- Check that your API key matches your web app account\n"
    result_text += "- Try logging out and back in to the web app\n\n"

    result_text += '**"Slack authorization failed" error:**\n'
    result_text += "- Ensure you have admin permissions in the Slack workspace\n"
    result_text += "- Check that the Slack workspace allows third-party apps\n"
    result_text += "- Try the OAuth flow again with a different workspace\n\n"

    return [TextContent(type="text", text=result_text)]


def format_refresh_configurations_response(
    configurations: List[Dict[str, Any]], total_elements: int
) -> List[TextContent]:
    """Format configuration refresh response."""
    result_text = "# Slack Configurations Refreshed\n\n"
    result_text += f"**Found {total_elements} Slack configuration(s)**\n\n"

    if not configurations:
        result_text += "## No Configurations Found\n\n"
        result_text += "If you just completed the OAuth flow and don't see any configurations:\n\n"
        result_text += (
            "1. **Wait a moment** - it may take a few seconds for the configuration to appear\n"
        )
        result_text += "2. **Check the web app** - ensure you saw a success message\n"
        result_text += "3. **Try again** - run this refresh command again\n"
        result_text += (
            "4. **Start over** - use `slack_oauth_workflow(action='initiate_oauth')` if needed\n\n"
        )
        result_text += "**Troubleshooting:**\n"
        result_text += "- Verify OAuth completed successfully in browser\n"
        result_text += "- Check for any error messages in the Revenium web app\n"
        result_text += "- Ensure you have the correct permissions in Slack\n"
    else:
        result_text += "## Available Configurations\n\n"

        for i, config in enumerate(configurations, 1):
            config_id = config.get("id", "Unknown")
            name = config.get("name", "Unnamed Configuration")
            # Use correct API field names from the actual response
            channel_name = config.get("channelName", "N/A")
            team_name = config.get("teamName") or config.get("team", {}).get(
                "label", "Unknown Workspace"
            )
            created_date = config.get("created", "Unknown")

            result_text += f"### {i}. {name}\n"
            result_text += f"- **ID:** `{config_id}`\n"
            result_text += f"- **Workspace:** {team_name}\n"
            result_text += f"- **Channel:** {channel_name}\n"
            result_text += f"- **Created:** {created_date}\n\n"

        result_text += "## Next Steps\n\n"
        result_text += "**Set a default configuration:**\n"
        result_text += "```\nslack_configuration_management(action='set_default_configuration', config_id='CONFIG_ID')\n```\n\n"

        result_text += "**View detailed configuration:**\n"
        result_text += "```\nslack_configuration_management(action='get_configuration', config_id='CONFIG_ID')\n```\n\n"

        result_text += "**Create alerts with Slack notifications:**\n"
        result_text += "- Use any alert creation tool (they now support Slack automatically)\n"
        result_text += "- Slack notifications will be sent using your default configuration\n"

    return [TextContent(type="text", text=result_text)]


def format_check_new_configurations_response(
    configurations: List[Dict[str, Any]], total_elements: int
) -> List[TextContent]:
    """Format check new configurations response."""
    result_text = "# Checking for New Slack Configurations\n\n"

    if total_elements == 0:
        result_text += "## No Configurations Found\n\n"
        result_text += "No Slack configurations are currently available.\n\n"
        result_text += "**If you just completed OAuth:**\n"
        result_text += "- The configuration may still be processing\n"
        result_text += "- Wait 10-30 seconds and try again\n"
        result_text += "- Check the Revenium web app for any error messages\n\n"
        result_text += "**To try OAuth again:**\n"
        result_text += "```\nslack_oauth_workflow(action='initiate_oauth')\n```\n"
    else:
        result_text += f"## Found {total_elements} Configuration(s)\n\n"

        # Show the most recent configuration first (assuming they're sorted by creation date)
        latest_config = configurations[0] if configurations else None
        if latest_config:
            name = latest_config.get("name", "Unnamed Configuration")
            # Use correct API field names from the actual response
            team_name = latest_config.get("teamName") or latest_config.get("team", {}).get(
                "label", "Unknown Workspace"
            )
            channel_name = latest_config.get("channelName", "N/A")
            config_id = latest_config.get("id", "Unknown")
            created_date = latest_config.get("created", "Unknown")

            result_text += "### Most Recent Configuration\n"
            result_text += f"**{name}**\n"
            result_text += f"- **Workspace:** {team_name}\n"
            result_text += f"- **Channel:** {channel_name}\n"
            result_text += f"- **Created:** {created_date}\n"
            result_text += f"- **ID:** `{config_id}`\n\n"

            result_text += "**Quick Actions:**\n"
            result_text += f"- Set as default: `slack_configuration_management(action='set_default_configuration', config_id='{config_id}')`\n"
            result_text += (
                "- View all: `slack_configuration_management(action='list_configurations')`\n"
            )

        if total_elements > 1:
            result_text += f"\n**Total configurations available:** {total_elements}\n"
            result_text += (
                "Use `slack_configuration_management(action='list_configurations')` to see all.\n"
            )

    return [TextContent(type="text", text=result_text)]


def get_oauth_examples_text() -> str:
    """Get examples text for Slack OAuth workflow."""
    return """# Slack OAuth Workflow Examples

## Basic OAuth Flow

### 1. Initiate OAuth
```python
slack_oauth_workflow(action="initiate_oauth")
```

### 2. Check OAuth Status
```python
slack_oauth_workflow(action="refresh_configurations")
```

### 3. Check for New Configurations
```python
slack_oauth_workflow(action="check_new_configurations")
```

## Troubleshooting

### Get Detailed Instructions
```python
slack_oauth_workflow(action="get_oauth_instructions")
```

## Complete Setup Workflow

### Step-by-Step Setup
1. **Start OAuth**: `slack_oauth_workflow(action="initiate_oauth")`
2. **Complete in browser** (follow the provided link)
3. **Check status**: `slack_oauth_workflow(action="refresh_configurations")`
4. **Set default**: Use `slack_configuration_management` to set default

### Custom Return Page
```python
slack_oauth_workflow(
    action="initiate_oauth",
    return_to="/custom/page"
)
```

## Integration with Other Tools

### After OAuth Completion
```python
# List new configurations
slack_configuration_management(action="list_configurations")

# Set default configuration
slack_configuration_management(
    action="set_default_configuration",
    config_id="new-slack-config-id"
)
```
"""


def get_oauth_capabilities_text() -> str:
    """Get capabilities text for Slack OAuth workflow."""
    return """# Slack OAuth Workflow Capabilities

## Tool Overview
Comprehensive OAuth workflow management for Slack integrations with guided setup, status checking, and troubleshooting support.

## Available Actions

### OAuth Management
- **initiate_oauth**: Start OAuth workflow and get authorization URL (with critical login warning)
- **refresh_configurations**: Refresh and display current configurations after OAuth
- **check_new_configurations**: Check for new configurations and show most recent
- **get_oauth_instructions**: Get detailed setup instructions and troubleshooting

### Discovery Actions
- **get_examples**: Get working examples and usage patterns
- **get_capabilities**: Get this comprehensive capabilities documentation

## Parameters

### Required Parameters
- **action** (string): Action to perform (see Available Actions above)

### Optional Parameters
- **return_to** (string): Page to return to after OAuth completion (default: /alerts/alerts-configuration)
- **dry_run** (boolean): Validation-only mode (default: false)

## OAuth Flow Process
1. **Initiate**: Get OAuth URL (with critical login warning)
2. **Login**: MUST be logged into Revenium before clicking OAuth link
3. **Authorize**: Complete Slack authorization in browser
4. **Verify**: Check OAuth status to confirm completion
5. **Configure**: Refresh configurations and set defaults

## Integration Points
- **Configuration Management**: Works with slack_configuration_management for setup
- **Alert Management**: Enables Slack notifications in alert creation
- **Environment Configuration**: Uses REVENIUM_APP_BASE_URL for OAuth URLs (which is set by default to the standard URL)

## Error Handling
- Structured error responses with actionable suggestions
- Validation of all parameters before execution
- Graceful handling of OAuth failures and network issues
- Clear guidance for common OAuth problems

## Troubleshooting Support
- Permission issues guidance
- Network connectivity problems
- Browser compatibility issues
- OAuth callback handling problems
"""
