# Changelog

All notable changes to the Revenium MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-08-28

### Added
- `manage_customers`: org-unit (department) lookup (list_org_units) — the source of ids for every ORG_UNIT filter
- `manage_customers`: team attribution identity policy and verified domains (get/update_attribution_identity_policy, list/add/remove_verified_domain), with per-privilege 403 messages — adding a domain is platform-operator-only and says so
- `manage_customers`: per-team PR-health thresholds (get/update_pr_health_settings, read-merge-write)
- `business_analytics_management`: developer PR-health report (get_pr_health) — aging/rotting by inactivity, drafts separate, estimates labeled
- `business_analytics_management`: Claude Enterprise seat census (get_seat_utilization) — vendor-withheld counts render as unavailable (never 0), an empty census reports no connection
- `business_analytics_management`: provider metering-coverage report (get_coverage_ratio) — hidden spend, trend as a signed pp delta, coding-assistant presence flag
- `manage_metering`: effort, model_host and subscriber_email_source on submitted transactions; transaction detail shows model execution and re-rated cost provenance (clientReportedCost)
- `manage_ai_insights`: scope a run to one department (filter_org_unit_id, filter_include_descendants)
- `manage_cost_controls`: department guardrails — ORG_UNIT dimension, preview_org_unit_group, and a per-email blocked summary
- `manage_tools`: agenticJobId on tool usage events, joining tool cost to its job
- Strict ingestion mode: allow_ticket_jobs opt-out
- OAuth (clerk mode): RFC 9207 iss validation on authorization responses

### Changed
- Every list tool bounds its filter keys to what the endpoint declares; an unknown key is rejected naming the valid set instead of silently returning unfiltered data
- `manage_metering` transaction lookups include coding-assistant records by default and state the scope in every response (include_coding_assistants switches the view)
- Aggregations a report cannot honour are rejected with a clear message instead of returning mislabeled totals
- fastmcp 3.2.0 -> 3.4.7, mcp 1.25.0 -> 1.29.0

### Fixed
- `manage_customers`: the introspection schema describes the real create requirements per resource type
- `manage_metering`: transaction detail renders null token counts beside zero costs instead of failing
- `manage_alerts`: natural-language queries no longer send filter parameters the endpoint discards
- api_key mode: unknown or malformed API keys are classified as invalid tokens with a clear message instead of a generic validation error
- Analytics: the Foundry provider label is normalized consistently

## [0.4.0] - 2026-08-13

### Added
- `manage_metering`: ticket and skill attribution on AI transaction submissions — `ticket_id` plus `skill_name`, `skill_source`, `skill_kind`, `skill_plugin_name`, `skill_marketplace_name` and `skill_invocation_trigger`, validated client-side against the platform's real column caps and closed vocabularies so agents get structured errors instead of silent attribution loss
- `manage_jobs`: outcomeReason on outcome reporting, distinguishing why the job failed from why a revision was recorded
- `business_analytics_management`: cost-by-skill analytics (list_skills, get_skill), with the feature-flag 403 and empty-window 404 explained instead of surfaced as raw errors
- `manage_customers`: team internal-marketplace settings (get_marketplace_settings, update_marketplace_settings with add/remove/replace)
- Business analytics: model-sources and task-types filter dimensions

### Changed
- `manage_metering`: accepted providers derive from the platform's model catalog (tenant-keyed cache) instead of a hardcoded enum; model validation uses the catalog's exact-match lookup and the new distinct-providers endpoint
- `manage_cost_controls`: get_enforcement_rules documents per-group balances (groupBreakdown)
- `manage_products`: list filtering is honest — real server-side query, exact filters.name matching across pages, unknown filter keys rejected, bounded scans say so when truncated

### Fixed
- `manage_ai_insights` list_feedback: parses the endpoint's bare-array wire shape; pagination is honest end to end (consumable continuation cursors, explicit end-of-results, truncation flags)
- `manage_products`: create_simple's documented name/description parameters are reachable through the MCP boundary; responses tolerate entries missing the now-optional id field
- Delete confirmations echo the request id across all tools
- Update actions preserve unspecified fields (merge semantics pinned across every widened write endpoint)

## [0.3.1] - 2026-07-26

### Changed
- Removed the unused revenium-middleware-openai dependency

## [0.3.0] - 2026-07-24

### Added
- `manage_agents` tool: agent registry (list, get, create, update, delete, list_discovered) plus read-only squad observability (list_squads, list_squad_executions, get_squad, get_squad_timeline)
- `manage_cost_controls` tool: AI spend guardrails (CRUD) with enforcement visibility (list_enforcement_events, get_enforcement_rules)
- Business analytics: task/profitability/spend-mover actions (get_task_costs, get_task_completion, get_task_performance, get_profit_margins, get_top_movers, get_token_breakdown, get_team_costs, get_vendor_costs, get_token_vs_tool_cost, get_trace_cost_distribution)
- Business analytics: get_filter_options(dimension=...) discovers valid filter values; get_unpaid_invoice_totals; read-only billing (list_invoices, list_refunds, list_period_charges); costSources filter on get_agent_costs; real transaction volume via get_transaction_count
- `manage_alerts`: reset_budget for cumulative-usage alerts; get_budget_portfolio and get_budget_progress reads
- `manage_customers`: lookup_user and lookup_subscriber by exact email
- `manage_subscriptions`: get_billed_amount and get_quota_consumed reads
- Tenant ingestion diagnostics: list ingestion failures and a guarded strict-ingestion-mode toggle; per-pathway data-ingestion status in check_system_status
- Server-side query search on sources, completions and tool-events listings
- HTTP transport: sliding-window rate limiting on MCP and OAuth endpoints
- api_key mode: per-request team selection via the X-Revenium-Team-Id header
- clerk mode: caller JWT forwarded downstream, Redis-backed OAuth client storage for multi-replica deployments, structured auth events

### Changed
- `system_health` and quick diagnostics are AUTH_MODE-aware (clerk deployments no longer report false criticals)
- Error responses carry resource-scoped suggestions and preserve upstream 400 detail; not-found lookups return promptly (retry-on-empty is opt-in)
- fastmcp pinned exactly; container images install the locked dependency set

### Fixed
- Auth failures now set `isError:true` on `manage_tools`, `manage_agents`, `manage_cost_controls` and `manage_ai_insights`
- `manage_ai_insights` exposes its real description in `tools/list`
- `manage_tools` accepts string `unitPrice`/`upTo` (GET round-trip) without TypeError
- `get_tool_costs` renders real tool names and costs; `get_api_endpoints` documents the real completions wire contract
- `manage_alerts`: the documented THRESHOLD payload now creates successfully instead of being rejected by the tool's own validator
- Analytics and insights requests target the host matching the configured environment instead of silently defaulting to production
- clerk-mode OIDC login no longer rejected (upstream audience dropped, granted scopes restored); the OAuth Redis client store honors `rediss://` TLS
- Dry-run/live parity restored on sources, alerts and subscriptions; `create_simple` dry-run previews show the real payload
- Out-of-range `page`/`size` values get a structured validation error instead of echoing corrupted values
- `manage_workflows` reports explicit `workflow_type` and real `created_at` timestamps
- Pydantic binding errors on newer fastmcp versions translate to clean structured errors instead of framework tracebacks
- Metering validation results cache correctly across manager instances (content-addressed cache keys)
- Hosted multi-tenant correctness: per-request credentials reach the data plane; handlers fail closed without tenant context

## [0.2.11] - 2026-06-04

### Added
- `/health` (liveness) and `/ready` (readiness) endpoints on the HTTP transport, exempt from auth, with a cached upstream reachability probe
- Automatic `Idempotency-Key` headers on metering submissions so client retries do not double-record transactions
- Container deployment: Dockerfile and docker-compose stack (HTTPS via Caddy), documented in README and `.env.example`

### Changed
- Invalid `AUTH_MODE`/`TRANSPORT_MODE` combinations (`clerk`+`stdio`, `api_key`+`stdio`) now fail fast at startup with a clear error
- `manage_metering` validation message for `task_id` now states the field is silently ignored by the API rather than causing a 400; use `trace_id` instead
- New dependency: `cachetools>=5.3.0` (api_key validation cache)

## [0.2.10] - 2026-05-22

### Added
- `manage_ai_insights` tool exposes the Revenium AI Insights API with actions `list_investigators`, `get_run`, `list_runs`, `list_feedback`, `trigger_run`, and `submit_feedback`
- Cursor-based auto-pagination on `manage_ai_insights.list_runs` and `list_feedback`
- Automatic idempotency keys on `manage_ai_insights.trigger_run` so retries do not double-fire recommendation runs
- `manage_ai_insights.get_run` returns a slim payload by default; pass `slim=false` for the full record

### Changed
- API failures returning `application/problem+json` (RFC 7807) are now mapped to structured tool errors with the upstream `code` field preserved, instead of opaque HTTP envelopes

## [0.2.9] - 2026-05-21

### Added
- `time_to_first_token` field on the `manage_metering` submission schema, grouped under streaming performance
- `has_more` pagination flag and per-source breakdown on `manage_metering` analytics responses

### Changed
- `manage_metering` analytics egress now filters high-cardinality fields out of responses surfaced to coding-assistant integrations
- `analyze_cost_anomalies` output renders as Markdown with nested time/entity summary subsections instead of a flat string
- `get_agent_costs` aggregates duplicate rows by agent name so the same agent under different IDs collapses into one row
- `revenue_metric_by_organization` now uses the new analytics endpoint, matching the rest of the analytics surface
- `get_user_costs` is hidden from `manage_tools_analytics` when the new-analytics-API flag is off
- `manage_workflows` dry-run and live execution paths share one schema and persist `workflow_id` consistently

### Fixed
- `lookup_transactions` no longer hangs when called with an empty-string `transaction_id`
- Invalid-action errors on `manage_metering` list all 12 actions instead of just 7
- `manage_metering` rejects zero tokens, zero `duration_ms`, and empty-string `transaction_id` at the boundary with a structured error
- `manage_products` errors propagate so the MCP envelope correctly marks `isError=true`
- `manage_alerts` decorator propagates `ToolError` and `ReveniumAPIError` instead of swallowing them
- `manage_metering_elements.create_from_template` returns a clear message when the element already exists as a system element instead of a misleading failure

### Removed
- Deprecated `organizationId`/`productId` fields removed from the AI metering MCP surface; use the canonical field names

### Security
- API keys redacted in all server log output (request logs, error logs, debug logs)
- Error responses sanitized so `raw_response_debug` payloads no longer leak to MCP clients on API failures

## [0.2.8] - 2026-05-07

### Added
- "Did you mean?" suggestions when a tool argument name is mistyped (e.g. `id` → `product_id`)
- `error_reason` field exposed on `manage_metering.get_submission_capabilities` and `get_field_documentation` Optional Fields

### Fixed
- `manage_metering.list_ai_models` and `search_ai_models` now reject non-numeric `page`/`size` with a structured error instead of an uncaught Python `TypeError`
- `manage_subscriptions`, `manage_products`, `manage_customers`, `manage_metering_elements`, and `manage_subscriber_credentials` now validate `page`/`size` at the tool boundary, including `size=0` and `MAX_INT` edge cases
- `manage_jobs` translates float, out-of-range, and non-numeric `page` values into a structured 400 response
- HTTP error responses no longer surface Python dict-repr trailers (e.g. `<msg> - {'error': '<msg>'}`) or internal `Error ID: <name>_<digits>` tokens
- Tool argument errors raised at the framework signature-binding layer are translated to a clean `ToolError` envelope, eliminating `errors.pydantic.dev` URLs and `call[<tool>]` framing on common typos
- `analyze_cost_anomalies` now accepts string `min_impact_threshold` and rejects invalid values with a structured error
- `manage_alerts.get` returns a structured "Alert not found" instead of an unhandled HTTP failure
- `business_analytics.get_api_key_costs` and `get_cost_summary` now aggregate rows whose masked label collides into one row per label with summed cost, share, and a `note: aggregated N untracked sources`
- `manage_customers` organization update now preserves the `parent` field
- `manage_products.update` partial-update semantics now match the create/update validators
- `manage_sources` type normalization now consistent across `create` and `update`
- `manage_subscriptions` list/get/update/search responses now normalize backend `"undefined"` placeholders in nested resource blocks (resource type inferred from the self link, label cleared, locale-formatted dates dropped)
- `manage_subscriptions` key-actions list now matches the dispatcher (no orphan or missing actions)
- `manage_metering.submit` rejects malformed `transaction_id` values at the boundary and rejects unknown provider values with a structured error
- `manage_alerts` capabilities are backfilled with Operators and Alert Types from canonical enums (no `Unknown` values surfaced)
- `manage_metering_elements` capabilities are backfilled with Element Types from the canonical set
- `manage_tools` JSON precision and action-validation hardening across the surface
- `list_ai_models` prose summary now reports the catalog `totalElements` rather than just the current page length

### Changed
- Auth-failure responses now use a consistent 401-shape `ToolError` envelope (`error_code=UNAUTHORIZED`) across all tools, replacing tool-specific failure shapes
- `manage_jobs` responses no longer include HAL `_links` envelopes
- `manage_tools` `meter_event` capability now points at `manage_metering` for subscriber-credential attribution

### Removed
- `requestDuration` metering element template (collided with the system element)
- Contradictory `task_id` entry from `get_submission_capabilities`

### Security
- Auth-failure messages no longer reference the `REVENIUM_API_KEY` environment variable literal

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

[0.3.0]: https://github.com/revenium/revenium-mcp/compare/v0.2.11...v0.3.0
[0.2.11]: https://github.com/revenium/revenium-mcp/compare/v0.2.10...v0.2.11
[0.2.10]: https://github.com/revenium/revenium-mcp/compare/v0.2.9...v0.2.10
[0.2.9]: https://github.com/revenium/revenium-mcp/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/revenium/revenium-mcp/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/revenium/revenium-mcp/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/revenium/revenium-mcp/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/revenium/revenium-mcp/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/revenium/revenium-mcp/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/revenium/revenium-mcp/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/revenium/revenium-mcp/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/revenium/revenium-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/revenium/revenium-mcp/compare/v0.1.27...v0.2.0
[0.1.27]: https://github.com/revenium/revenium-mcp/releases/tag/v0.1.27

[0.5.0]: https://github.com/revenium/revenium-mcp/releases/tag/v0.5.0
