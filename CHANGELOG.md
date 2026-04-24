# Changelog

All notable changes to the Revenium MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.7] - 2026-04-23

### Added
- Cost-by-user analytics via the new `get_user_costs` action on `manage_tools_analytics`, with optional filters for agents, providers, models, users, and cost sources
- Tool cost analytics actions on `manage_tools_analytics` for per-tool spend breakdowns
- USD currency labels on numeric `metricResult` values returned by analytics responses, including values nested in lists and dictionaries
- `REVENIUM_LOG_FILE` environment variable for routing server logs to a file
- Structured request and error logging in the HTTP client for easier downstream parsing

### Fixed
- `manage_tools` analytics now surface a clear configuration error when `REVENIUM_APP_BASE_URL` drifts from the API URL, instead of returning a misleading "Invalid API key" message
- `manage_tools.create` now correctly injects `teamId` into the request payload
- `manage_tools` analytics actions now expose `period` and `group` as first-class parameters and no longer leak raw Pydantic validation errors
- `manage_tools` returns a structured error when `page` or `size` are passed with the wrong type, instead of surfacing an uncaught Python `TypeError`
- `manage_tools.get` with a non-existent id now returns a structured "Tool not found" error rather than HTTP 500
- `manage_tools.search` now honors the `query` parameter and filters results accordingly, instead of returning every tool regardless of query
- `manage_alerts` exposes `periodDuration` and `triggerAfterPersistsDuration` as documented flat parameters
- `manage_alerts` accepts `alert_id` as an alias for `anomaly_id`, resolving the parameter naming inconsistency across actions
- `manage_metering.submit` rejects unknown provider values with a structured error instead of silently accepting them
- `manage_jobs` translates out-of-range `page` values (including `MAX_INT`) into a structured 400 response instead of an unhandled HTTP 500
- Pagination validation messages now reference the calling action name, making errors easier to trace

## [0.2.6] - 2026-04-14

### Fixed
- Corrected URL routing for 17 `manage_tools` actions that returned 404 errors
- Dry-run validation now rejects non-semantic version strings before server submission
- Client-side enum validation aligned with server-accepted values

## [0.2.5] - 2026-04-09

### Added
- Analytics engine migration to high-performance endpoints with full search filters
- Jobs and Outcomes management tool with ROI analytics and conversion funnel tracking
- Tool Registry management tool with pricing tier support
- New `RELATIVE_CHANGE` detection rule type with natural language operator support
- 8 additional `manage_tools` operations exposed as MCP actions
- Capability metadata for `manage_tools`
- Email and name parameters for subscriber credential management
- Streaming status, response quality score, and stop reason fields for metering

### Fixed
- AI model search now uses server-side filtering instead of client-side pagination
- Pagination corrected in model provider validation and cost estimation
- Slack guided setup no longer displays incorrect workspace or channel information
- Subscription updates correctly extract client email from associated label
- Organization and team updates now include required organization context
- Stale tool references corrected in Slack notification messages
- Resource type now correctly identified in error responses

### Security
- Credential data no longer exposed in dry-run preview output

### Changed
- FastMCP upgraded from 2.x to 3.x (>=3.2.0,<4.0.0)
- JSON string preprocessing support in `manage_tools`

## [0.2.4] - 2026-04-01

No functional changes. Changelog formatting update only.

## [0.2.3] - 2026-04-01

### Added
- Distributed tracing support for transaction correlation (operation type, session ID, parent trace, and additional context fields)

### Fixed
- FastMCP version pinned to prevent incompatible upgrades
- Field naming consistency in customer management
- Error handling improvements in Slack setup, resource lookups, and task processing
- Privacy policy and contact URL corrections

## [0.2.2] - 2025-11-24

### Changed
- Upgraded FastMCP to >=2.10.0 for MCP protocol compliance
- Standardized all API endpoints to api.revenium.ai
- Renamed MCP slash commands to duration-based naming (e.g., rm-summary-24h)

### Fixed
- API version in discovery metadata corrected to v2
- Default profile in discovery metadata aligned with actual defaults
- Tool count corrected for starter profile

## [0.2.1] - 2025-11-10

### Fixed
- Minor improvements and stability fixes

## [0.2.0] - 2025-11-10

### Changed
- Internal architecture improvements

## [0.1.27] - 2024-11-14

### Added
- Initial release of Revenium MCP Server
- Alert management tools for AI cost monitoring and threshold detection
- Slack integration for real-time notifications
- AI cost analytics with anomaly detection and trend analysis
- Usage-based billing tools
- Profile system (Starter/Business) for tool selection
- Support for Claude Code, Cursor, and Augment IDE integration
- Configuration via environment variables
- System diagnostics and transaction verification tools

[0.2.7]: https://github.com/revenium/revenium-mcp/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/revenium/revenium-mcp/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/revenium/revenium-mcp/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/revenium/revenium-mcp/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/revenium/revenium-mcp/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/revenium/revenium-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/revenium/revenium-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/revenium/revenium-mcp/compare/v0.1.27...v0.2.0
[0.1.27]: https://github.com/revenium/revenium-mcp/releases/tag/v0.1.27
