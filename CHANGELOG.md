# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.2] - 2025-11-24 - Public Release

### Changed
- Upgraded FastMCP dependency from >=0.1.0 to >=2.10.0 (MCP Spec 2025-06-18 compliance)
- Standardized repository for public release
- Restored flexible parameter handling for alert updates (P2/P3 improvements)
- Updated all API endpoints to api.revenium.ai
- Standardized all email contacts to support@revenium.io
- Renamed slash commands to duration-based naming (e.g., rm-summary-24h)

### Fixed
- API version in discovery metadata now correctly shows v2
- Default profile in discovery metadata now matches actual default
- Fixed tools_count to reflect starter profile default (7 tools)

### Documentation
- Added MCP Specification 2025-06-18 compliance documentation
- Added slash commands table to README
- Moved internal working documents to .internal/

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

### Features

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

### Documentation
- Installation guides for uvx, venv, and IDE integration
- Profile selection documentation
- Configuration reference
- Troubleshooting guide

[Unreleased]: https://github.com/revenium/revenium-mcp/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/revenium/revenium-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/revenium/revenium-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/revenium/revenium-mcp/compare/v0.1.27...v0.2.0
[0.1.27]: https://github.com/revenium/revenium-mcp/releases/tag/v0.1.27
