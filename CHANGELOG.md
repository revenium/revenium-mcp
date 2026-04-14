# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.5] - 2026-04-09

### Added
- MCP analytics migration to high-performance endpoints
- RELATIVE_CHANGE detection rule support with NLP mappings and operator validation
- Jobs & Outcomes management tool — manage_jobs with ROI analytics
- Tool Registry management tool — manage_tools with pricing tiers
- ROI analytics and conversion funnel support in manage_jobs
- 8 missing client methods exposed as manage_tools MCP actions
- Capabilities metadata and quick start guide for manage_tools
- Missing email/name params and resolver actions to manage_subscriber_credentials
- Missing is_streamed, response_quality_score, stop_reason fields to manage_metering

### Fixed
- search_ai_models to use server-side filtering instead of local pagination
- Same pagination bug in validate_model_provider and estimate_transaction_cost
- guided_setup and detect_and_recommend showing Unknown Workspace and #N/A
- Subscription update: extract clientEmailAddress from client.label
- Organization/team update: inject tenantId in default_fields
- Parameterize "Invalid Anomaly ID" error with correct resource type
- Update 3 stale slack_setup_assistant references in email_verification.py

### Changed
- Upgraded FastMCP from >=2.10.0,<3.0.0 to >=3.2.0,<4.0.0
- JSON string preprocessing support in manage_tools
- README updated for Jobs & Outcomes, Tool Registry, and RELATIVE_CHANGE alerts

## [0.2.4] - 2026-04-01

### Changed
- Remove `[Unreleased]` heading from CHANGELOG.md

## [0.2.3] - 2026-04-01

### Added
- Tracing fields support for MCP Server (10 new trace fields)
- Branch protection bypass alert workflow

### Fixed
- Pin FastMCP to <3.0.0 to prevent breaking upgrades
- Customer_id field name inconsistency
- ValidationError kwargs in slack_setup_assistant
- create_resource_not_found_error kwargs in call sites
- Variable-shadowing TypeError in _process_task_data
- Remove deprecated FastMCP `dependencies` kwarg
- Privacy policy URL corrections in documentation
- Bump pytest-asyncio to >=0.23.0 for async test support

### Changed
- Raise unit test coverage from 26% to 81%
- Test quality audit: remove 120 vacuous tests, rewrite 196 tautological tests with behavioral assertions
- Raise CI coverage threshold from 70% to 80%

### Changed
- Add project context documentation
- Update contact info and URLs

## [0.2.2] - 2025-11-24 - Public Release

### Changed
- Upgraded FastMCP dependency from >=0.1.0 to >=2.10.0 (MCP Spec 2025-06-18 compliance)
- Standardized repository for public release
- Restored flexible parameter handling for alert updates
- Updated all API endpoints to api.revenium.ai
- Standardized all email contacts to support@revenium.io
- Renamed slash commands to duration-based naming (e.g., rm-summary-24h)

### Fixed
- API version in discovery metadata now correctly shows v2
- Default profile in discovery metadata now matches actual default
- Fixed tools_count to reflect starter profile default (7 tools)

### Added
- MCP Specification 2025-06-18 compliance documentation
- Slash commands table to README

## [0.2.1] - 2025-11-10

### Changed
- Minor improvements and bug fixes

## [0.2.0] - 2025-11-10

### Changed
- Version bump with improvements

## [0.1.27] - 2024-11-14

### Added
- MCP server for Revenium API integration
- Alert management tools for AI cost monitoring
- Slack integration for notifications
- AI cost analytics and anomaly detection
- Usage-based billing tools (Business profile)
- Profile system (Starter/Business) for tool selection
- Support for Claude Code, Cursor, Augment IDE integration
- Comprehensive configuration via environment variables
- System diagnostics tools
- Transaction lookup and verification
- Cost trend analysis

### Added
- Installation guides for uvx, venv, and IDE integration
- Profile selection documentation
- Configuration reference
- Troubleshooting guide

**Starter Profile (7 tools):**
- Alert management for cost thresholds and spike detection
- Slack integration for notifications
- AI business analytics and cost trends
- AI metering integration guidance
- System diagnostics

**Business Profile (15 tools):**
- All Starter profile tools
- Product management for usage-based billing
- Customer/organization management
- Subscription management
- Subscriber credential management

[0.2.5]: https://github.com/revenium/revenium-mcp/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/revenium/revenium-mcp/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/revenium/revenium-mcp/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/revenium/revenium-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/revenium/revenium-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/revenium/revenium-mcp/compare/v0.1.27...v0.2.0
[0.1.27]: https://github.com/revenium/revenium-mcp/releases/tag/v0.1.27
