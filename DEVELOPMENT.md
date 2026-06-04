# Development Guide

This guide provides detailed information for developers working on the Revenium MCP Server.

## Prerequisites

- Python 3.11 or higher
- Virtual environment tool (venv, virtualenv, or conda)
- MCP-compatible client for testing (Claude Desktop, Claude Code, etc.)
- Git for version control

## Development Setup

### 1. Clone and Setup Environment

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/revenium-mcp.git
cd revenium-mcp

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install package in editable mode with development dependencies
pip install -e ".[dev]"
```

### 2. Environment Configuration

Create a `.env` file in the project root:

```bash
# Create .env file for development
cat > .env << EOF
# Required
REVENIUM_API_KEY=your_revenium_api_key
REVENIUM_TEAM_ID=your_team_id

# Optional - tool profile (starter or business)
TOOL_PROFILE=starter

# Optional - for AI routing feature
# OPENAI_API_KEY=your_openai_api_key
# AI_ROUTING_ENABLED=true

# Optional - debug logging
# LOG_LEVEL=DEBUG
EOF
```

**Important Notes:**
- Never use `export` commands - they're session-specific and will be lost when you close the terminal
- The server automatically loads `.env` when running from the virtual environment
- Default API endpoint is `https://api.revenium.ai` (no need to set REVENIUM_BASE_URL unless using a different endpoint)
- See `.env.example` for all available configuration options

## Testing

### Manual Testing with MCP Clients

**Claude Code:**
```bash
# Add to MCP settings
claude mcp add revenium-dev \
  -e REVENIUM_API_KEY=your_key \
  -e REVENIUM_TEAM_ID=your_team \
  -e REVENIUM_BASE_URL=https://api.revenium.ai \
  -- /path/to/revenium-mcp/venv/bin/python -m revenium_mcp_server
```

**Direct Execution:**
```bash
# Start server manually
python -m revenium_mcp_server
```

**Expected Output:**
```
Revenium MCP Server v0.2.2 ready with 15 tools
FastMCP 2.13.1
Server name: Revenium MCP Server v0.2.2
Transport: STDIO
```

**Known Startup Warnings (can be ignored):**
- `DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated` - Will be fixed in next release
- `WARNING: Auto-discovery failed: API key lacks required permissions` - Normal for dev environment

### Unit Testing

**Current Status:** Some tests require additional dependencies not yet in pyproject.toml

```bash
# Install missing test dependencies (temporary workaround)
pip install psutil

# Run all tests
pytest

# Run with coverage
pytest --cov=src/revenium_mcp_server --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run with verbose output
pytest -v

# Run specific test
pytest tests/test_auth.py::test_auth_config_validation
```

**Note:** If pytest fails with `ModuleNotFoundError: No module named 'psutil'`, install it manually as shown above. This will be added to dev dependencies in the next release.

### Testing AI Routing (Optional Feature)

```bash
# Add to your .env file:
cat >> .env << EOF
AI_ROUTING_ENABLED=true
OPENAI_API_KEY=sk-...
EOF

# Run server and verify self-metering
python -m revenium_mcp_server

# Check that OpenAI usage appears in Revenium dashboard
```

## Code Quality Standards

### Python Style Guidelines

- **PEP 8 Compliance**: Follow Python Enhancement Proposal 8
- **Type Annotations**: Use type hints for all function signatures
- **Docstrings**: Document all public functions, classes, and modules
- **Line Length**: Maximum 100 characters (soft limit)
- **Function Length**: Keep functions under 50 lines when possible
- **Cyclomatic Complexity**: Maximum complexity of 10

### Code Formatting

**Note:** The current codebase is in the process of being formatted. Many files may not yet pass black checks.

```bash
# Format code with black (applies formatting)
black src/ tests/

# Check formatting without making changes
black --check src/ tests/

# Sort imports
isort src/ tests/
```

**For new code:**
- Always run `black` before committing
- Ensure your changes pass `black --check`

**For existing code:**
- Large formatting changes should be separate PRs
- Focus on formatting only the files you're modifying

### Linting

```bash
# Style/lint
flake8 src/
ruff check src/ tests/

# Mypy regression gate (the type-check command CI runs)
uv run --extra dev python scripts/check_mypy_regressions.py

# Syntax smoke check (catches malformed merges; not a type gate)
python -m compileall -q src
```

#### Mypy posture

The repo's `[tool.mypy]` config is strict (`disallow_untyped_defs`,
`warn_return_any`, etc.) but the codebase carries a large pre-existing type
error backlog. Running raw `mypy src/` is therefore **expected to fail** on
current `main` until the BACK-1271 cleanup epic is complete.

The short-term gate is `scripts/check_mypy_regressions.py`. It diffs the
current mypy output against `scripts/mypy-baseline.txt` and only fails when
new errors are introduced — existing backlog errors do not block merges.

To regenerate the baseline after intentional improvements:

```bash
uv run --extra dev python scripts/check_mypy_regressions.py --update
```

`compileall` is a syntax-only smoke check (catches malformed merge conflict
resolution and similar) and does **not** validate types.

## Architecture Guidelines

### MCP Server Structure

```
src/revenium_mcp_server/
├── __init__.py
├── enhanced_server.py     # Main MCP server entry point
├── auth.py                # Authentication configuration
├── client.py              # Revenium API client
├── constants.py           # Centralized constants
├── tools_decomposed/      # Individual MCP tools
├── capability_manager/    # Tool capability discovery
└── ai_routing/           # Optional AI query routing
```

### Key Principles

1. **Centralized Configuration**: All constants in `constants.py`
2. **API Version Consistency**: Use API v2 endpoints consistently
3. **Error Handling**: Use structured error responses
4. **Logging**: Log to stderr (not stdout) for stdio transport
5. **Type Safety**: Full type annotations for maintainability

### Configuration Constants (`constants.py`)

The `constants.py` module serves as the single source of truth for all configuration constants used throughout the MCP server. This centralized approach prevents duplication and ensures consistency.

**Available Constants:**

```python
# API Configuration
DEFAULT_BASE_URL = "https://api.revenium.ai"  # Base URL without /meter or /profitstream paths
API_SUPPORTED_VERSIONS = ["v2"]               # Current API version - all endpoints use v2
AUTHENTICATION_METHODS = ["api_key"]          # Supported authentication methods

# Rate Limiting
API_RATE_LIMIT_PER_MINUTE = 1000  # Requests per minute limit
API_BURST_LIMIT = 100              # Burst request limit

# Profile Configuration
DEFAULT_PROFILE = "starter"        # Default tool profile if not specified
MCP_SERVER_VERSION = get_package_version()  # MCP server version - dynamically retrieved
```

**Usage Guidelines:**

1. **Import constants instead of hardcoding values:**
   ```python
   # Good
   from revenium_mcp_server.constants import DEFAULT_BASE_URL, API_SUPPORTED_VERSIONS

   # Bad
   base_url = "https://api.revenium.ai"  # Don't hardcode
   ```

2. **When to use constants vs environment variables:**
   - Use **constants** for: Default values, API versions, rate limits, system-wide settings
   - Use **environment variables** for: User-specific configuration (API keys, team IDs, custom URLs)

3. **Modifying constants:**
   - Only modify constants when changing system-wide defaults
   - Document the reason for changes in commit messages
   - Update all dependent code and tests
   - Never override constants at runtime - use environment variables instead

4. **Rate limiting constants:**
   - `API_RATE_LIMIT_PER_MINUTE` and `API_BURST_LIMIT` are used by the capability discovery system
   - These values are reported to MCP clients in system capabilities
   - Modify only if Revenium API rate limits change

5. **Version management:**
   - `MCP_SERVER_VERSION` is dynamically retrieved from package metadata
   - It automatically reflects the version in `pyproject.toml`
   - Used in system capabilities and startup messages
   - Never hardcode version numbers elsewhere

**Example Usage:**

```python
from revenium_mcp_server.constants import (
    DEFAULT_BASE_URL,
    API_SUPPORTED_VERSIONS,
    API_RATE_LIMIT_PER_MINUTE,
    MCP_SERVER_VERSION
)

# Use in API client initialization
client = ReveniumClient(
    base_url=os.getenv("REVENIUM_BASE_URL", DEFAULT_BASE_URL),
    api_version=API_SUPPORTED_VERSIONS[0]
)

# Use in capability reporting
capabilities = {
    "server_version": MCP_SERVER_VERSION,
    "rate_limits": {
        "requests_per_minute": API_RATE_LIMIT_PER_MINUTE
    }
}
```

### Adding New MCP Tools

```python
# Example tool in tools_decomposed/
from mcp.types import TextContent

async def new_tool_handler(action: str, **kwargs) -> list[TextContent]:
    """Handle new tool operations.

    Args:
        action: The action to perform
        **kwargs: Additional parameters

    Returns:
        List of TextContent responses
    """
    # Implementation
    pass
```

## Commit Guidelines

### Commit Message Format

```
type(scope): brief description

Detailed explanation of what changed and why.

BREAKING CHANGE: description of breaking change (if applicable)

Fixes #issue_number
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Test additions or updates
- `refactor`: Code refactoring
- `chore`: Maintenance tasks
- `perf`: Performance improvements

**Examples:**
```bash
git commit -m "feat(tools): add transaction lookup pagination support"
git commit -m "fix(auth): handle missing API key gracefully"
git commit -m "docs(README): clarify AI routing optional feature"
```

## Pull Request Process

### Before Submitting

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/descriptive-name
   ```

2. **Make Changes**
   - Follow code quality guidelines
   - Add tests for new functionality
   - Update documentation

3. **Run Quality Checks**
   ```bash
   # Format your changes
   black src/ tests/
   isort src/ tests/

   # Style/lint
   flake8 src/
   ruff check src/ tests/

   # Mypy regression gate (raw `mypy src/` is expected to fail until the
   # BACK-1271 cleanup epic completes — use the gate to confirm your change
   # does not introduce new type errors)
   uv run --extra dev python scripts/check_mypy_regressions.py

   # Run tests
   pytest
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "type(scope): description"
   ```

5. **Push to Fork**
   ```bash
   git push origin feature/descriptive-name
   ```

### Pull Request Description Template

```markdown
## Description
Brief description of changes

## Motivation
Why these changes are needed

## Changes
- List of specific changes
- Each on its own line

## Testing
How these changes were tested

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] Code formatted with black
- [ ] No breaking changes (or documented)
```

## Debugging

### Enable Debug Logging

```bash
# Add to .env file
echo "LOG_LEVEL=DEBUG" >> .env

# Run server
python -m revenium_mcp_server
```

### Common Issues

**Issue: ModuleNotFoundError**
```bash
# Reinstall in editable mode
pip install -e .
```

**Issue: ModuleNotFoundError: No module named 'psutil'**
```bash
# Install missing dependency (temporary workaround)
pip install psutil
```

**Issue: API Authentication Fails**
```bash
# Verify .env file exists and has API key
cat .env | grep REVENIUM_API_KEY

# Test API connection
# For development environment:
curl -H "x-api-key: YOUR_KEY_FROM_ENV" https://api.revenium.ai/profitstream/v2/api/sources/ai/anomaly

# For production environment:
curl -H "x-api-key: YOUR_KEY_FROM_ENV" https://api.revenium.ai/profitstream/v2/api/sources/ai/anomaly
```

**Issue: MCP Client Can't Connect**
- Check server logs for stderr output
- Verify Python path in MCP client config
- Ensure virtual environment is activated
- Check that .env file is in project root

**Issue: Server shows deprecation warnings**
- Known issue - warnings can be safely ignored for now
- Will be fixed in upcoming release
- Does not affect functionality

## MCP Specification Compliance

This server implements [MCP Specification 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18).

### Key Requirements

- **Framework**: FastMCP 2.10.0+
- **Transport**: stdio (standard input/output)
- **Protocol**: JSON-RPC 2.0
- **Logging**: All logs to stderr (stdout reserved for JSON-RPC)

### Validation

```bash
# Verify FastMCP version
pip show fastmcp

# List installed tools in your MCP client
# (Server runs via stdio transport - no standalone CLI flags)
```

## API Endpoints

### Development Environment
- **Base URL**: `https://api.revenium.ai`
- **Use for**: Testing, development, staging

### Production Environment
- **Base URL**: `https://api.revenium.ai`
- **Use for**: Production deployments, released versions

### Testing Endpoints

```bash
# Test anomaly endpoint
curl -H "x-api-key: YOUR_KEY" \
  https://api.revenium.ai/profitstream/v2/api/sources/ai/anomaly

# Test products endpoint
curl -H "x-api-key: YOUR_KEY" \
  https://api.revenium.ai/profitstream/v2/api/products
```

## Release Process

### Version Bumping

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md` with changes
3. Update version in `src/revenium_mcp_server/version.py`
4. Create release commit:
   ```bash
   git commit -m "chore: bump version to X.Y.Z"
   ```

### Publishing to PyPI

```bash
# Build distribution
python -m build

# Check package
twine check dist/*

# Upload to PyPI (maintainers only)
twine upload dist/*
```

## Additional Resources

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18)
- [FastMCP Documentation](https://pypi.org/project/fastmcp/)
- [Revenium API Documentation](https://docs.revenium.io)
- [Python Packaging Guide](https://packaging.python.org/)

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/revenium/revenium-mcp/issues)
- **Questions**: support@revenium.io
- **Security**: Follow [Security Policy](./SECURITY.md)
