[![PyPI version](https://img.shields.io/pypi/v/revenium-mcp.svg)](https://pypi.org/project/revenium-mcp/)
[![Python Versions](https://img.shields.io/pypi/pyversions/revenium-mcp.svg)](https://pypi.org/project/revenium-mcp/)
[![Documentation](https://img.shields.io/badge/docs-revenium.io-blue)](https://docs.revenium.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-purple)](https://modelcontextprotocol.io/specification/2025-06-18)

# Revenium MCP Server

**Connect AI agents to Revenium for cost tracking, alerting, and usage-based billing**

Once you've connected your AI applications to Revenium using any of the supported middleware libraries or via direct API integration, this MCP server allows agents to directly interact with your Revenium account. Connect Claude, OpenAI, or any MCP-compatible AI assistant to Revenium to configure AI cost alerts & tracking as well as usage-based billing for AI products.

##  Features

### AI Cost Tracking & Alerting - Never Be Surprised by Unexpected AI Costs Again
- Ask AI agents to **set up AI cost alerts to avoid unexpected costs**
- Ask AI agents to track their own costs with Revenium as they carry out actions within your application
- Ask Revenium to **calculate AI cost & usage trends over time** and set up alerts to immediately send slack or email notifications when anomalies occur
- Quickly **investigate the reasons for AI cost spikes**. Identify abnormal changes in spending by agent, API key, product, customer, and more.
- Use AI agents to **integrate Revenium metering into your applications** if not using Revenium's pre-built SDKs

### Usage-based Billing & Chargebacks (Optional)
If or when you're ready to turn AI costs into AI revenue, the Revenium MCP will be there to help quickly make the transition.

- Ask your agent to manage all elements of usage-based billing & cost chargebacks
- Use agents to manage products, customers, subscriptions, and subscriber credentials

### Profile-Based Tool Selection
The MCP provides the appropriate tools for each use case depending on your chosen startup profile:
- **Starter Profile (7 tools):** Cost monitoring, alerts, analytics, AI metering integration
- **Business Profile (15 tools):** All Starter tools plus product management, customer management, subscriptions, billing

## Getting Started

### For Claude Code Users (Recommended)

1. **Install uv:**
   ```bash
   pip install uv
   ```

2. **Add to Claude Code:**
   ```bash
   claude mcp add revenium \
     -e REVENIUM_API_KEY=hak_your_api_key_here \
     -- uvx revenium-mcp
   ```

Done! Claude Code will manage the configuration.

### For Local Development/Testing

1. **Install uv:**
   ```bash
   pip install uv
   ```

2. **Create .env file:**
   ```bash
   cat > .env << EOF
   REVENIUM_API_KEY=hak_your_api_key_here
   TOOL_PROFILE=starter
   EOF
   ```

3. **Run the server:**
   ```bash
   uvx revenium-mcp
   ```

See [Installation](#installation) for Cursor, Augment, and other integrations.

## MCP Specification

Implements [Model Context Protocol](https://modelcontextprotocol.io/specification/2025-06-18) version **2025-06-18**.

- **Framework:** FastMCP 2.10+
- **Transport:** stdio
- **Protocol:** JSON-RPC 2.0

## Requirements

### Prerequisites

- **Python 3.11+** with pip
- **Your Revenium API key** (get one at [ai.revenium.io](https://ai.revenium.io))
- **Optional:** [uv/uvx](https://github.com/astral-sh/uv) for easier installation

### System Requirements

- Operating System: macOS, Linux, Windows (with WSL)
- Network: Internet connection for API communication
- MCP Client: Claude Code, Cursor, Augment IDE, or any MCP-compatible client

## What Gets Tracked

When you use this MCP server, the following data flows between your AI assistant and Revenium:

### Data Sent to Revenium

- API requests for cost analytics and queries
- Alert configuration requests (thresholds, notifications)
- Customer/product management operations (when using Business profile)
- Transaction lookup queries

### Data Retrieved from Revenium

- AI usage metrics and costs (grouped by provider, model, customer, etc.)
- Alert status and notification configurations
- Product/subscription information (Business profile)
- Analytics data and cost trends
- Anomaly detection results

### Data NOT Collected

- ❌ Your AI assistant's conversations or prompts
- ❌ Prompt content (unless you explicitly submit transactions for metering)
- ❌ Personal data beyond what you configure in Revenium
- ❌ File contents or local data

### Privacy & Security

- All communication uses your Revenium API key for authentication
- Data is transmitted securely over HTTPS
- API keys are never logged or exposed in tool responses
- Data handling is subject to [Revenium's privacy policy](https://revenium.io/privacy)

## AI Query Routing (Optional Feature)

The MCP server includes an **optional** AI-powered query routing feature for natural language interpretation. **This feature is disabled by default** and is not required for normal operation.

### What It Does

When enabled, the server can use OpenAI's API to interpret natural language queries and route them to appropriate tools. This is an experimental feature that adds intelligent query understanding.

### Self-Metering

When AI routing is enabled, the MCP server automatically tracks its own OpenAI usage back to your Revenium account:
- Uses `revenium-middleware-openai` to meter its own API calls
- Creates transactions visible in your Revenium dashboard
- Provides full transparency into the MCP server's operational costs

### Enabling AI Routing

AI routing is **disabled by default**. To enable it, add to your `.env` file:

```bash
# .env
REVENIUM_API_KEY=hak_your_api_key_here
OPENAI_API_KEY=sk-your_openai_key_here
AI_ROUTING_ENABLED=true
AI_MODEL_NAME=gpt-3.5-turbo  # Optional: default model
```

Then run:
```bash
uvx revenium-mcp
```

**Note:** Without AI routing enabled, the MCP operates normally using direct tool calls. No OpenAI API key or additional costs are required.

## Environment Configuration

The MCP server uses environment variables for configuration. **The method you use depends on your setup:**

| Setup | Method | When to Use |
|-------|--------|-------------|
| **Claude Code** | `-e` flag in `claude mcp add` | Integrating with Claude Code (most common) |
| **Cursor/Augment** | JSON config `"env": {...}` | Integrating with Cursor or Augment IDE |
| **Local testing** | `.env` file | Testing the server directly from command line |

**Important:** Don't mix methods. Choose the one that matches your use case:
- If using Claude Code, you only need the `-e` flag (no .env file or export needed)
- If testing locally, use a `.env` file (no export needed)
- Never use `export` - it's session-specific and gets lost when you close the terminal

## Installation

### Install Python Package

**Option 1: Installation with uvx** (Recommended for local testing)
```bash
# Install uv if you don't have it
pip install uv

# Create .env file
cat > .env << EOF
REVENIUM_API_KEY=hak_your_api_key_here
TOOL_PROFILE=starter
EOF

# Run the server (automatically loads .env)
uvx revenium-mcp
```

**Option 2: Package Installation in Virtual Environment**

```bash
# Create and activate virtual environment
python -m venv revenium-mcp-env
source revenium-mcp-env/bin/activate  # On Windows: revenium-mcp-env\Scripts\activate

# Install package
pip install revenium-mcp

# Create .env file for configuration
cat > .env << EOF
REVENIUM_API_KEY=hak_your_api_key_here
TOOL_PROFILE=starter
EOF

# Run the server (automatically loads .env from current directory)
python -m revenium_mcp_server
```

**Note:** The `.env` file should be in the directory where you run the server. Never commit `.env` to version control.

### Choose Your Profile & Start the Server

The MCP server supports two profiles to match your use case:

| Profile | Tools | Target Users | Use Cases |
|---------|-------|--------------|-----------|
| **Starter** (default) | 7 tools | Cost monitoring & alerts | Cost analysis, AI transaction metering |
| **Business** | 15 tools | Full platform | Product & subscription management, usage-based billing, comprehensive analytics |

The server uses the **Starter** profile by default. To use the **Business** profile, set the `TOOL_PROFILE` environment variable:

**With uvx and .env file:**
```bash
# Starter Profile (7 tools) - Cost monitoring, alerts, AI metering integration (default)
cat > .env << EOF
REVENIUM_API_KEY=hak_your_api_key_here
TOOL_PROFILE=starter
EOF
uvx revenium-mcp

# Business Profile (15 tools) - Usage-based billing & AI Analytics
cat > .env << EOF
REVENIUM_API_KEY=hak_your_api_key_here
TOOL_PROFILE=business
EOF
uvx revenium-mcp
```

### For Claude Code

Choose one of the following integration methods. Both use the **Starter** profile by default. To use the **Business** profile, add `-e TOOL_PROFILE=business` to the command:

**Option 1: Installation with uvx**
```bash
# Install uv if you don't have it
pip install uv

# Starter profile (default)
claude mcp add revenium \
  -e REVENIUM_API_KEY=hak_your_api_key_here \
  -- uvx revenium-mcp

# Business profile (for advanced features)
claude mcp add revenium \
  -e REVENIUM_API_KEY=hak_your_api_key_here \
  -e TOOL_PROFILE=business \
  -- uvx revenium-mcp
```

**Option 2: Installation with python virtual environment**
```bash
# Create and activate virtual environment
python -m venv revenium-mcp-env
source revenium-mcp-env/bin/activate  # On Windows: revenium-mcp-env\Scripts\activate

# Install package
pip install revenium-mcp

# Add to Claude Code using venv python (starter profile - default)
claude mcp add revenium \
  -e REVENIUM_API_KEY=hak_your_api_key_here \
  -- ./revenium-mcp-env/bin/python -m revenium_mcp

# For business profile, add the environment variable:
claude mcp add revenium \
  -e REVENIUM_API_KEY=hak_your_api_key_here \
  -e TOOL_PROFILE=business \
  -- ./revenium-mcp-env/bin/python -m revenium_mcp
```

#### Claude Code Slash Commands

Optional prompt shortcuts for Claude Code users. Copy the [slash commands](https://github.com/revenium/revenium-mcp/tree/HEAD/.claude/commands) to your project's `.claude/commands/` folder.

| Command | Description |
|---------|-------------|
| `/rm-summary-1h` | Spending summary (last hour) |
| `/rm-summary-24h` | Spending summary (last 24 hours) |
| `/rm-summary-7d` | Spending summary (last 7 days) |
| `/rm-summary-30d` | Spending summary (last 30 days) |
| `/rm-anomalies-24h [threshold]` | Detect cost anomalies (24h, default $50) |
| `/rm-anomalies-7d [threshold]` | Detect cost anomalies (7d, default $50) |
| `/rm-anomalies-30d [threshold]` | Detect cost anomalies (30d, default $50) |
| `/rm-alert-budget-daily [threshold]` | Create daily budget alert (default $100) |
| `/rm-alert-per-transaction [threshold]` | Create per-transaction alert (default $5) |
| `/rm-customers-30d` | Top customers by cost (30 days) |

---

### For Cursor / Augment IDE (or any IDE allowing MCP JSON import)

**Install uv:**
```bash
pip install uv
```

**Configure MCP server:**

1. Open Cursor/Augment settings (Ctrl/Cmd + ,) | (Cmd + Shift + P for Augment)
2. Navigate to Extensions → MCP or create `~/.cursor/mcp.json` | for Augment, import JSON below into MCP settings
3. Add server configuration:

**Standard Configuration:**
```json
{
  "mcpServers": {
    "revenium": {
      "command": "uvx",
      "args": ["revenium-mcp"],
      "env": {
        "REVENIUM_API_KEY": "hak_your_api_key_here"
      }
    }
  }
}
```

## Basic Usage

After installation, the MCP server provides tools to your AI assistant. Simply ask natural language questions:

### Cost Monitoring Examples

```
"Summarize my AI costs for the last month"
"Show me a breakdown of costs by provider"
"Alert me when monthly costs for Anthropic exceed $500"
"Why did my costs spike yesterday?"
```

### Slack Integration Examples

```
"Set up Slack notifications for cost alerts"
"Send all cost alerts to #ai-spending channel"
"Create a spike detection alert that notifies my team on Slack"
```

### Analytics Examples

```
"Analyze cost anomalies in the last 7 days"
"Find API key anomalies using aggressive sensitivity"
"Show me cost trends for the last month"
"Detect what caused my cost increase yesterday"
```

### AI Metering Integration

```
"Get Python integration guide for AI transaction metering"
"Help me integrate this Python AI function with Revenium"
"Generate test transaction data and verify it's processing correctly"
```

See [AI Cost Analytics & Alerting Tools](#ai-cost-analytics--alerting-tools) for complete tool descriptions.

## Advanced Usage

The MCP server provides different tool sets based on your selected profile:

### Alert Management

Set up intelligent monitoring for costs, usage, and performance metrics.
- Create budget threshold and spike detection alerts
- Get notified via Slack or email when patterns change
- *Example: "Alert me when monthly costs for Anthropic exceed $500"*
- *Example: "Create a spike detection alert when token use exceeds 1,500,000 tokens per hour"*
- *Example: "Alert when my error rate exceeds 5% every 5 minutes"*
- *Example: "Set up cost per transaction monitoring so any single AI call costing more than $1.50 triggers an immediate Slack alert"*

### Slack Integration
- *Example: "Set up a Slack notification channel for Revenium alerts"*
- *Example: "Add a new slack channel for all customer spending alerts"*
- *Example: "Send all product spending anomalies to the Slack channel #product-spend-alerts."*

### AI Business Analytics
Analyze costs, usage patterns, and performance.
- Cost trend analysis and breakdowns
- *Example: "Summarize my costs for the last day/week/month and highlight any anomalies"*
- *Example: "Explain why costs grew last week"*
- *Example: "Show me a breakdown of AI costs last month by provider/customer/product/agent"*

#### Common Use Cases

**"Why did my costs spike yesterday?"**
- *"Analyze cost anomalies in the last 7 days focusing on abnormal spending by model or API key"*
- *"Detect what caused my cost increase yesterday. Only focus on anomalies larger than $20 vs. the norm"*

**"Find anomalies across all dimensions"**
- *"Show me cost anomalies in the last month across all providers, models, agents, API keys, and customers"*
- *"Analyze all dimensions for cost spikes above $150 in the past 30 days"*

**"Detect small but significant anomalies to identify early changes in behavior before they become large issues"**
- *"Find API key anomalies in the last week using aggressive sensitivity"*

### AI Metering Management
Track AI usage, token consumption, and transaction data with comprehensive integration guidance.
- Get assistance creating a new custom integration from your AI agents to Revenium
- Get comprehensive implementation guidance with working code examples for Python and JavaScript
- Submit AI transaction data and verify successful processing

- *Example: "Get Python integration guide with working code examples for AI transaction metering"*
- *Example: "Get JavaScript integration guide with Revenium documentation"*
- *Example: "Check the status of transaction tx_12345"*
- *Example: "Help me integrate this python AI function with Revenium's AI metering API"*
- *Example: "Generate test transaction data from our application and ensure all metadata is properly mapped in Revenium."*

---

## Usage-Based Billing Tools (Business Profile Only)

###  Product Management
Create and manage your AI products, pricing tiers, and billing models.
- Design usage-based or subscription pricing
- Design chargeback models so that all AI spending is invoiced to the correct internal department
- Set up free tiers and graduated pricing for SaaS products
- *Example: "Create a Gold Tier AI product with $199 per month base fee plus usage-based pricing that charges 1.10x the actual AI costs"*
- *Example: "Create a new product called 'Smart Analytics' with usage-based pricing"*
- *Example: "Set up a free tier with 1000 API calls, then charge a 25% premium on my AI costs for every call"*
- *Example: "Show me the number of subscribers for each of my products"*

###  Customer Management
Handle customer relationships, organizations, and user hierarchies.
- Manage customer or internal organizations used for cost attribution
- Create & manage subscribers (internal or external)
- Track customer usage

- *Example: "List all organizations and their subscription status"*

###  Subscription Management
Control customer subscriptions, billing cycles, and plan changes.
- Create and modify customer subscriptions
- Track subscription analytics
- *Example: "Create a monthly subscription for customer ABC Corp to the product 'analytics-suite'"*
- *Example: "Show me all active subscriptions to the AI Analytics product"*
- *Example: "List subscriptions that are about to expire this month"*

## Configuration Options

### Required Configuration

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `REVENIUM_API_KEY` | ✅ | Your account API key from the API Keys page in Revenium | `hak_1234567890abcdef` |

### Automatically Loaded Values

These values are loaded from your account and can be overridden if needed:

| Variable | Override When | Example |
|----------|---------------|---------|
| `REVENIUM_TEAM_ID` | Multi-tenant environments | `ABC123x` |
| `REVENIUM_TENANT_ID` | Operating on behalf of different tenant | `DEF456n` |
| `REVENIUM_OWNER_ID` | Non-primary user scenarios | `GHI789z` |
| `REVENIUM_DEFAULT_EMAIL` | Custom alert email preferences | `alerts@company.com` |

### Optional Configuration

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `REVENIUM_BASE_URL` |  | API endpoint URL (defaults to main Revenium instance) | `https://api.revenium.ai` |
| `REVENIUM_APP_BASE_URL` |  | Defines which Revenium web application instance to use for Slack channel configurations (defaults to main Revenium instance) | `https://ai.revenium.io` |
| `LOG_LEVEL` |  | Logging verbosity level | `DEBUG` |
| `REQUEST_TIMEOUT` |  | API request timeout in seconds | `30` |

### Overriding Default Values in IDE / MCP Client (Advanced Use Cases)

You can override the automatically loaded values if needed:

**When you might need overrides:**
- Multi-tenant environments: Switching organizations in a multi-tenant Revenium installation
- Custom email preferences: Change default email address for alert configuration
- Custom API endpoints: When not using Revenium's default API endpoints

##  Troubleshooting

### Authentication Errors
- Verify your API key is correct and active
- Use the diagnostic tool to check configuration status
- Ensure the base URL is correct for your environment
- Check that the `/users/me` endpoint is accessible with your API key

### Configuration Priority
The system loads configuration values in this priority order:
1. **MCP client JSON configuration `env` section** (highest priority)
2. **System environment variables**
3. **Automatically loaded values** from Revenium's API

Use the `system_diagnostics` tool to see exactly which values are being used from each source.

### Common Issues

**Issue:** MCP server not appearing in AI assistant
**Solution:** Verify installation with `uvx revenium-mcp --version` and check MCP client configuration

**Issue:** Authentication errors
**Solution:** Verify API key based on your setup:

**For local development (.env file):**
```bash
# Check if .env exists and contains your key
cat .env | grep REVENIUM_API_KEY

# Verify the server can load it (run from project directory)
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('API Key:', os.getenv('REVENIUM_API_KEY', 'NOT FOUND')[:20] + '...')"
```

**For Claude Code:**
```bash
claude mcp list  # Verify configuration includes API key
```

**For Cursor/Augment:**
Check your MCP JSON config file includes `REVENIUM_API_KEY` in the `env` section.

**For any setup:**
Use the `system_diagnostics` tool to see exactly which configuration values are being used.

**Issue:** Tools not working as expected
**Solution:** Check you're using the correct profile (Starter vs Business) for your use case

## Documentation

For detailed documentation, visit [docs.revenium.io](https://docs.revenium.io)

Additional resources:
- [API Documentation](https://revenium.readme.io)
- [MCP Protocol Specification](https://modelcontextprotocol.io)

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines on:

- Reporting bugs
- Suggesting enhancements
- Submitting pull requests
- Development workflow

## Code of Conduct

This project adheres to a Code of Conduct to ensure a welcoming and inclusive community. See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) for details.

## Security

Security is a top priority. For security concerns, please see [SECURITY.md](./SECURITY.md) for:

- Our security policy
- How to report vulnerabilities
- Security best practices

## License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for full details.

## Support

For questions, issues, or feature requests:

- **Email:** support@revenium.io
- **Issues:** [GitHub Issues](https://github.com/revenium/revenium-mcp/issues)
- **Documentation:** [docs.revenium.io](https://docs.revenium.io)
- **Community:** [Revenium Discord](https://discord.gg/revenium) (coming soon)

## Development

### Local Development Setup

```bash
# Clone repository
git clone https://github.com/revenium/revenium-mcp.git
cd revenium-mcp

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies (including dev dependencies)
pip install -e ".[dev]"

# Create .env file for development
cat > .env << EOF
REVENIUM_API_KEY=hak_your_api_key_here
REVENIUM_TEAM_ID=your_team_id
LOG_LEVEL=DEBUG
EOF

# Verify .env is loaded
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(f'API Key loaded: {os.getenv(\"REVENIUM_API_KEY\", \"NOT FOUND\")[:20]}...')"

# Run tests
pytest

# Run linters
black .
isort .
mypy .
flake8
```

**Important:** Never commit your `.env` file. The repository includes `.env.example` as a template.

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=revenium_mcp_server --cov-report=html

# Run specific test file
pytest tests/test_auth.py
```

### Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed development guidelines including:

- Code style requirements
- Testing requirements
- Pull request process
- Release process

## Acknowledgments

Built by the Revenium team with contributions from the community.

Special thanks to:
- Anthropic for the Model Context Protocol specification
- The open-source community for MCP tooling and support
