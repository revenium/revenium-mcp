# Changelog

All notable changes to the Revenium MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.1] - 2026-10-19

### Added
- `business_analytics_management`: the cost actions that read the analytics API take start_date and end_date (yyyy-MM-dd, both days included, at most 366 days) in place of period, so a calendar month such as September 1 to 30 can be read the way the app's custom range reads it; the report header shows the exact range

### Changed
- The server depends on fastmcp 4.0.10 (was 4.0.0); its dependency set is unchanged. What the move fixes is under Fixed ("Every tool: a call with an argument the tool does not accept...")

### Fixed
- `manage_products`, `manage_sources`, `manage_customers`, `manage_metering_elements` and `manage_subscriptions` update: two updates of different fields on one record sent less than a second apart, one after the other or at the same time, both end up stored, instead of the second putting the first one's old values back while both answered success. This covers fields the stored record names (such as `name`, `description`, `plan`); a relationship sent by id (`parentId`, `subscriberId`, `productId`, `ownerId`, `teamId`) can still be put back by a quick second update, as before. An update the platform answers with another value than the one sent for a field is an error naming that field, with what was sent and what was stored, instead of a success
- `manage_alerts` update: an empty or blank required field (`name`, `periodDuration`, `alert_type`, `metric_type`, `operator_type`, `tracking_period`) is refused with "is required; send a value, or leave it out to keep the stored one" and nothing is sent, instead of reaching the platform; a null or blank `webhook_configurations` or `is_percentage` keeps the stored value instead of sending `[null]` or switching the percent flag off. `create_cumulative_usage_alert` creates a budget with a threshold of 0 instead of calling it missing, and refuses true or false as a threshold
- `manage_alerts` update: a null `name`, `alertType`, `metricType`, `operatorType`, `periodDuration` or `enabled` inside `anomaly_data` is refused by the dry run and the live update alike, with nothing sent, instead of a "Dry Run Successful" preview followed by a platform error; a null `isPercentage` or `minSampleCount` keeps the stored value and the update is reported as applied instead of "not fully updated"
- `manage_alerts` enable, disable, toggle_status, enable_multiple, disable_multiple, enable_all and disable_all: an alert whose stored values break a current platform rule (such as a provider alert on FIFTEEN_MINUTES, or a stored EQUAL_TO operator) is refused before anything is sent, naming the stored field and asking for an update first, instead of a raw platform error; a bulk action lists that alert as failed and switches the rest
- `manage_alerts` enable_multiple, disable_multiple, enable_all, disable_all and clear_all: a call where nothing succeeded and something failed is an error answer with the same summary, instead of a success answer reading "Successful: 0"; an alert the platform sends without a name is listed by its id, "<id> (no name)", instead of "None"
- `manage_alerts` create and validate: an alert built with `anomaly_data`, flat fields or `detection_rules` notifies every email and Slack channel it names, flat or nested, once each, instead of a detection_rules alert dropping them; with none named it notifies your default email, or is refused with the error flag when none is known, instead of being created to notify nobody. A Slack-only alert is sent as given, and the default Slack channel is never added. create_from_text sends the Slack channel you pass, or your default one, on every sentence, uses the `name` you pass, and refuses an argument it cannot apply, such as threshold or metric, instead of ignoring it
- `manage_alerts` create_from_text: the threshold is the number next to the money, percent or comparison words, so a digit in a name (p2, gpt-4, team-3) or in a window ("over 24 hours") no longer becomes the threshold, and "exceeds 10k" or "1.5 million" is read in full, while a word starting with m, k or b after a count ("5 models") is not a multiplier and a window written "15m" is not the threshold. "Add a second alert" no longer turns a token rate alert into a refused per-second one, while "per second", "1000 tokens a second", "50 requests/second" and "a second" followed by anything but an alert word ("a second at peak") still read as per second
- `manage_alerts` create_from_text: the number after budget, limit or cap, optionally followed by of, is or at, or capped at, is the threshold, so "alert me when the phase 2 budget of 500 is hit" and "team 3 budget 500" are created at 500 instead of 2 and 3, "5 percent", "5 pct" or "5 %" decides like "5%" and makes a percentage alert while a word such as "percentile" elsewhere in the text does not, and a number inside a name such as "budget 2026-Q1" is not the threshold; a text with two or more numbers that could each be the threshold and no word that says which, such as "alert when project 7 spend hits 300", is refused with an error naming them and asking which one is the threshold, and nothing is created.
- `manage_subscriptions` create: a quick create with no `clientEmailAddress` is refused, naming the field and keeping your other fields in the retry example, instead of billing a made-up `user-<time>@example.com` address. REVENIUM_DEFAULT_EMAIL still fills it when it holds a real address (not blank and not the `dummy@email.com` placeholder), and the preview and the create answer then say the address came from it; the preview's auto-generated list names only what was filled, and no description is generated
- `manage_subscriptions` create with `auto_generate=false`: a missing `product_id`, a missing `clientEmailAddress` and a preview whose product does not resolve are errors with the error flag set, instead of plain answers an assistant could read as a success
- `manage_subscriptions` update: a field the platform does not store on a subscription, such as `description`, `product_id` or `updated`, is refused with every such field named and nothing changed, instead of "updated successfully" for a value that was never kept; `subscription_data` that is not an object is refused too, and `name`, `expiration`, `clientEmailAddress` and `productId` update as before
- `manage_subscriptions` create: a request with only a top-level `name` is refused as missing `subscription_data` instead of creating a subscription on the first product with an invented address
- `manage_subscriptions` create: the answer names any field you sent that the platform does not store, for example "Not stored by the platform: description."
- `manage_subscriptions` search_subscriptions: a search by customer_name, subscriber_email or product_name carries `total_found_basis`, saying that total_found counts every subscription whose name, client username or email, organization name or product name contains the term, not only those matching on the field searched
- `manage_subscriptions` create: when you name no product, the "Which product?" retry example keeps every field you sent, and asks for `clientEmailAddress` only when you left it out
- `manage_subscriptions` subscription_nlp: "find popcorn subscriptions" and "search subscriptions with popcorn" search for `popcorn` instead of `popcorn s` and `s with popcorn`, and "show subscriptions for popcorn" or "list subscriptions for popcorn" search for that customer instead of listing every subscription
- `business_analytics_management`: get_token_breakdown narrowed to one provider, such as `providers: ["openai"]` or `providers: "openai"`, answers for that provider instead of failing with the platform's HTTP 400; two or more providers are sent as before
- `business_analytics_management`: get_token_breakdown and get_task_completion refuse a blank or empty `providers` or `agents` (such as `""`, `[]` or `[""]`) before any read instead of answering the unfiltered report as if it were narrowed, and get_coverage_ratio refuses a blank provider instead of covering every provider. list_invoices, list_refunds, list_period_charges and get_unpaid_invoice_totals refuse an argument they do not apply (such as invoice_id on list_invoices, period, filters or provider) and a blank filter such as `invoice_number: ""` or `pay_states: []`, instead of answering every invoice, refund or charge, or the whole outstanding total, as if narrowed; a blank amount still means no bound, and a false flag such as `dry_run: false` is still answered. list_period_charges refuses a `page` other than the first, since it pages with `cursor` and would answer the first page again
- `business_analytics_management`: get_agent_costs and get_api_key_costs list agents and API keys the platform reports at $0.00 or below, so "Agents Found" and "API Keys Found" match the platform's count; those rows carry no share
- `business_analytics_management`: get_agent_costs with filters.costSources answers MEAN, MAXIMUM and MINIMUM instead of refusing them, because the analytics route is asked for that aggregation beside the cost source
- `business_analytics_management`: get_cost_summary gives each of its five parts a time limit, whatever the request timeout; a part still reading then is named under Parts Not Read with the action that reads it alone, and the other parts are shown
- `business_analytics_management`: a credit in the ranked cost reports and the cost summary reads -$5.00 instead of $-5.00
- `business_analytics_management`: get_cost_summary's top lists show only rows that added cost; $0.00 and credit rows stay in the single-report actions and the total, and a part that was read with no such row says "none above $0.00"
- `business_analytics_management`: analyze_cost_anomalies with detect_new_entities and a min_new_entity_threshold names the threshold when nothing reached it, and says only sources that reached it are listed when some did, instead of saying nothing new appeared
- `business_analytics_management`: analyze_cost_anomalies new-entity detection on the newer analytics route says that only the 20 costliest API keys are named, and no longer reports the Other API keys group as a new or activated key
- `business_analytics_management`: analyze_cost_anomalies counts new and activated cost sources apart in the new-entity summary, so a source that resumed after idle baseline buckets is not counted as new
- `business_analytics_management`: analyze_cost_anomalies "Time groups analyzed" is the number of buckets the platform returned (per dimension when they differ), and the detect_new_entities parameter text names activated sources
- `manage_jobs`: a job id containing a slash is refused before any request, with a message saying job ids use only letters, digits, '.', '_' and '-', instead of the platform's bare "HTTP 400: Bad Request". get_job, get_job_transactions, get_job_roi, report_outcome, amend_outcome and append_outcome_metrics all refuse it the same way
- `manage_jobs` list_session_attributions: the session id is sent as one path segment, so a '?', '#' or '../' in it can no longer send the read to another endpoint or another resource; an id of '.' or '..', one containing a slash, or a blank one is refused before any request
- `manage_jobs` list_jobs: the heading names the creation dates sent ("Jobs created from ... to ... (page 1):", "... onward", "... up to ..."), or says no startDate or endDate was given and the list covers all creation dates, and the answer carries `filters_applied` with the filters actually sent
- `tool_introspection` and every tool's execution path: the metadata provider looked up for a tool is the one registered last, and a removed or cleared provider is no longer served, instead of the first provider ever looked up
- Every tool that takes `dry_run`: an empty `dry_run`, or any value that is not a clear off (absent, null, false, 0, "false", "no", "off"), now previews the action or is refused with the error flag set, instead of carrying out the delete and answering "deleted successfully". A `dry_run` placed inside a write payload such as `subscription_data`, `product_data` or `event_data` of `manage_tools` is refused, saying to send `dry_run=true` next to `action` when that action can preview, and otherwise how to see what it would affect, instead of being ignored while the write runs
- Every tool that calls the platform: a request that times out names the request method (the path is masked before the caller sees it), which phase ran out (connecting, waiting for the answer, sending, or waiting for a free connection) and how long it waited, instead of "Request failed:" with nothing after it. The caller's own API key or sign-in token is masked in every platform error the client reports, its logs included, if the platform ever repeats it
- `manage_sources` and `manage_workflows`: source create_from_text and workflow validate are removed and now get the normal unknown-action answer, which lists the real actions. create_from_text created a real source named "Source from text: ..." with type UNKNOWN in the caller's organization, with no preview, and the tool's capability list, introspection examples and unknown-action examples steered assistants to it; workflow validate only printed a deprecation notice as a success and checked nothing. Tool restore stays a hidden refusal (BACK-4806).
- `business_analytics_management`: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_cost_summary and the four tool cost reports refuse a `filters` object instead of answering with the whole report as if it were narrowed; their platform reports take no such filter. The refusal says to call again without filters and read the row wanted, and for tool costs names `manage_tools` get_cost_by_provider and get_cost_breakdown, where a provider or tool filter does apply. get_filter_options, get_capabilities and get_examples name only the reports whose filters take effect
- `business_analytics_management`: get_user_costs, get_department_costs and get_agent_costs refuse a blank, null or non-string filter value (such as `"users": ""` or `[""]`), and a filters object given as a blank string or list, instead of sending it upstream where the platform ignored it and answered with every user; real values are still sent exactly as typed
- `business_analytics_management`: every cost action applies a narrowing argument or refuses it, so none answers the whole report as if it were narrowed. get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_cost_summary, the tool cost reports and the user, department and agent reports refuse a top-level provider, providers, model, customer or agents argument; the user and department refusal says to pass it under filters. The analytics-pack actions (task, team, vendor, profit margin, top mover, token and trace reports), get_ai_assistant_team_medians, get_transaction_count, get_coverage_ratio and analyze_cost_anomalies refuse filters and any of those arguments they do not read; get_token_breakdown still applies providers, get_task_completion agents and get_coverage_ratio provider
- `business_analytics_management`: get_provider_costs, get_model_costs and get_customer_costs list the providers, models and customers the platform reports at $0.00, and "Providers Found" and the other counts include them, so an unpriced or unmetered provider no longer reads as never used. A credit that arrives as a negative cost is listed and counted in the total and in get_cost_summary's total; share is taken against the positive rows only
- `business_analytics_management`: get_filter_options with dimension users lists everyone get_user_costs lists for the same window, because it now asks for the same three cost sources instead of the platform's coding-assistant-only default; filters.costSources names a subset, and naming cost sources for another dimension is refused
- `business_analytics_management`: get_agent_costs with filters.costSources on a named period answers on the hosted server instead of refusing with advice to set a server setting; the filter reads the analytics API on every deployment, and the scope note says so. An unfiltered agent read keeps its route
- `business_analytics_management`: get_cost_summary reads its five parts at once and answers with the parts that came back, naming each part not read, its reason and the single-report action that retries it, instead of failing the whole summary on one slow report. When the provider part fails the total says not read rather than $0.00, and a failure is no longer answered with advice to check the period
- `business_analytics_management`: list_invoices, list_refunds and list_period_charges take a calendar day (yyyy-MM-dd, the whole UTC day, both days included) for start_date and end_date as well as an ISO-8601 instant with Z or an offset, instead of failing with the platform's HTTP 400. A lone start_date or end_date, a blank, unparseable or reversed date, or a date and time without a zone, is refused before the call with a short message marked as an error; a lone start_date no longer lists every invoice as if filtered
- `business_analytics_management`: list_invoices sends starting_amount and ending_amount as whole numbers, so filtering by amount works instead of failing for every value. 0 is kept, a blank amount is ignored, and a fraction or negative amount is refused with a message saying the filters take whole numbers
- `business_analytics_management`: a list_skills page past the last says so and names the pages that exist, instead of "No skills found for the given filters"
- `business_analytics_management`: every dollar figure prints with one rule, two decimals from a cent up and two significant digits below, so a fraction of a cent on get_vendor_costs, get_trace_cost_distribution, the cost timeseries and the formatter-built cost reports (get_provider_costs, get_department_costs and the rest) reads $0.0042 instead of $0.00. get_pr_health prints its two estimates in USD and describes avgCostPerMergedPr as the cost basis the estimates multiply instead of "the only cost figure the platform returns". list_invoices, list_refunds and list_period_charges print an amount such as 0.23200000000000004 as 0.232, dropping float noise beyond 15 significant digits and keeping the currency code
- `business_analytics_management`: get_seat_utilization stops calling the day before the latest census sync's day a gap; after a READ sync such days are said to have ended too recently for that sync to include them. get_pr_health multiplies the priced AI-assisted counts for its two dollar estimates instead of the full counts, shows the Priced since date beside them, and reads n/a with the cause when the platform returns no priced counts. The breakdown, queue, trend and follow-through help says which date each counts from, and `manage_customers` get_pr_health_settings explains that defaultCutoffDate sets where priced figures start only when the team has no cutoff of its own
- `business_analytics_management`: an aggregated report line with one metric shows the value alone (`- **Tasks Completed**: 3,457,734`) instead of repeating the metric name, and list_skills prints every row of the page, up to 100, with the page, the total and the call for the next page, instead of stopping at 50 rows
- `manage_alerts` create: an alert with a 30-day window (THIRTY_DAYS) is created for threshold alerts. SEVEN_DAYS and TWENTY_FOUR_HOURS, which the platform refuses, are refused with the error flag set and name WEEKLY or DAILY, the windows the platform takes instead; the alert capabilities list the same accepted windows
- `manage_alerts` update: clearing a persist wait with `trigger_after_persists_duration: null` (or an empty value) clears it instead of failing; a null `slack_config_id` clears the Slack link by sending an empty list instead of the text "None"; a null for alert_type, metric_type, operator_type or tracking_period is refused before the update is sent. A refused request whose platform message mentions JSON now reads "Request Data Refused", and on alert updates the advice points at the refused value instead of missing fields
- `manage_alerts` create_threshold_alert: a threshold of 0 creates the alert instead of reporting the threshold as missing; and a negative threshold is refused with the message "Invalid threshold value: -5.0; use a number, zero or more"
- `manage_alerts` get_examples: the relative-change examples say periods shorter than FIFTEEN_MINUTES are refused instead of promising they are clamped to DAILY
- `manage_customers` accepts `user_data`, `organization_data`, `subscriber_data` and `team_data`, and `manage_metering_elements` accepts `overrides` on create_from_template, as their help says, instead of refusing them as unrecognized; a per-type argument sent alongside `resource_data`, or alongside another type's data argument, wins, on create, validate and the update preview alike. `manage_subscriptions` no longer advertises a `date_range` on get_metrics that it never read
- `manage_workflows`: the tool description names the actions it has (get_workflow_templates, start, next_step, complete_step, list, get) instead of create, execute and get_suggestions, which do not exist, and its error hints point at start instead of create
- A JSON string in a data or list argument that does not parse is now an error on every tool, with the error flag set, so an assistant no longer reads a refused create or update as a success. This covers `manage_alerts`, `manage_sources`, `manage_workflows`, `manage_subscriber_credentials`, `manage_products`, `manage_customers`, `manage_subscriptions`, `manage_metering_elements`, `manage_tools`, `manage_agents` and `manage_cost_controls`, inside `params` too; an `agent_data`, `control_data` or `filters` that is not an object and an `anomaly_ids` that is not an array are errors the same way. A list argument such as `tags`, `transaction_ids`, `email_addresses` or `providers` sent as a string that starts like JSON but is not a JSON array is refused the same way instead of being stored or filtered on as raw text; a plain single value such as `"openai"` still works as before, and a single value that itself starts with a bracket goes inside an array, as in `["[draft] notes"]`. A refused data argument is no longer quoted back or logged: the refusal says where parsing failed or which JSON type was needed instead, so a secret inside one is not echoed. Valid JSON strings and native objects work as before
- `system_setup`, `system_diagnostics` and `slack_management` stop advertising options that changed nothing (`include_sensitive`, `format_output`, `include_recommendations`, `show_detailed_analysis`, `show_environment`, `include_setup_guidance`, `suggest_smart_defaults`, `validate_format`, `skip_prompts`) in their schema, capabilities and help; calls that still send them work as before
- `business_analytics_management`: get_task_costs, get_task_completion, get_task_performance, get_profit_margins, get_top_movers, get_token_breakdown, get_team_costs, get_vendor_costs, get_token_vs_tool_cost and get_trace_cost_distribution refuse a period they cannot read, such as NINETY_DAYS, with an error naming the supported periods, instead of answering the last 30 days under the period asked for; a lowercase period such as seven_days is read as SEVEN_DAYS and labelled so (BACK-4626)
- `business_analytics_management`: over a start_date/end_date range, and on servers that read the analytics API for every period, get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs and get_cost_summary answer MEAN, MAXIMUM and MINIMUM with the platform's average, largest and smallest figures instead of the total labelled as the aggregation; get_user_costs, whose platform report has totals only, refuses MEAN, MAXIMUM and MINIMUM instead of returning totals under those labels (BACK-4641)
- `business_analytics_management`: get_api_key_costs and the cost summary's top API keys give each key one row with its cost over the whole period, in cost order, instead of one row per twelve-hour slice; keys whose names share their first and last four characters are no longer added together under one shortened name, "API Keys Found" counts distinct keys with cost, and both answers shorten key names the same way (first and last four characters) (BACK-4623)
- `business_analytics_management`: get_provider_costs, get_model_costs, get_customer_costs, get_agent_costs and the cost summary's top lists combine the period's time slices by the aggregation asked for: MAXIMUM is the largest slice, MINIMUM the smallest, MEAN the average of the slices and no longer grows with the length of the period, and the ranking follows that figure; spellings of one provider within a slice count as one slice, and an idle slice no longer hides an entity that spent elsewhere in the period; TOTAL answers are unchanged (BACK-4639)
- `manage_alerts`: an alert created without an email never notifies a placeholder address. create_from_text notifies the email you pass, else your own, and an alert action that cannot find any email now returns an error that says how to supply one
- Every tool: a request with dry_run on an action that cannot preview (for example deleting a subscription, subscriber credential or alert, disabling an alert, or changing a team's verified domains) is refused with the error flag and changes nothing, instead of being carried out and reported as a success. The refusal names the actions of that tool that do preview. Reads such as list and get, and every business_analytics_management action, also refuse dry_run, since none of them has a preview
- `manage_alerts`: clear_all, enable_all and disable_all run only when confirm is true or a yes such as "true" or "yes"; a placeholder such as "null", "none" or "n", or any other value, gets the confirmation request and changes nothing
- `manage_alerts`: clear_all says "Anomalies Not Cleared" when it deleted nothing, and names each alert it could not delete with the platform's reason, at most ten
- `manage_alerts`: get_metrics no longer answers "HTTP 404: Not Found" for every alert, which read as "this alert does not exist". The platform has no per-alert metrics read, so the action is gone from the tool's actions and help, and a call to it says so and names get, get_budget_progress and the alert history list instead
- `manage_alerts`: the alert rule list, a single rule and the create confirmation show a percentage threshold as "20.0% (percentage)" and a cost threshold in dollars ("$6,321.87"), so a 20 percent rule no longer reads as $20; a PERCENT_INCREASE or PERCENT_DECREASE rule reads as a percentage even when it was stored without isPercentage, error and quality rate thresholds read as percentages, and the percent operators read "increases by" and "decreases by"
- `manage_alerts`: an alert history list or query the platform refuses now carries the platform's reason and names the filter it refused (for example "Invalid date format" and filters.start), with the error flag set, instead of only "Failed to list alerts"; a window the server refuses itself is an error too; the filters help and get_capabilities say start and end take a yyyy-MM-dd day or a timestamp with Z or an offset
- `business_analytics_management`: a request the tool or the platform refuses (a bad period or date, a missing period, an unknown skill id or action, a failed platform read) comes back marked as an error, keeping its guidance but no longer pasting the platform's raw response (its timestamp, path or Java type names); a blank start_date or end_date on list_invoices, list_refunds or list_period_charges is refused before the platform is called, naming the field, while a blank amount filter still lists as before. A get_skill period with no usage, and an anomaly report where only some dimensions could be read, stay normal answers
- `business_analytics_management`: analytics error help no longer tells the customer to check a rebuild status that does not exist
- All tools: when the platform asks an API key to wait (HTTP 429 with a stated wait, such as the pause after many failed requests), a call returns at once saying how many seconds to wait and sends nothing more to the platform until then, instead of retrying for about 15 seconds and failing; a 429 is never resent. On the hosted server, signing in during the wait is answered with HTTP 429 and the seconds instead of a bad-token 401. On a local server, a pause at the first call is reported as a pause instead of a missing team setting, any 429 there is not resent, and the team is found again once the wait has passed
- All tools: a read the platform answers with a server error is retried once, after one second, instead of three times; writes keep their configured retries
- Analytics reads: a production customer whose analytics read is refused sees the platform's own reason and is no longer told the key likely belongs to a dev or staging environment. The hint to set REVENIUM_APP_BASE_URL appears only for a non-production platform address, names a real analytics address pairing, and its server log line is no longer lost to a logging format error
- `business_analytics_management` get_pr_health and `manage_customers` get_pr_health_settings: the report states the date its counts start from when the platform sends it, so a team with no cutoff date sees that only pull requests opened in the last six months are counted; the settings answer shows defaultCountsSince and no longer says an empty cutoff date means no cutoff
- `business_analytics_management`: get_pr_health_engineers sorts by mergedPrs, aiShare, rotRate and departmentLabel, and get_pr_health_pull_requests by repo, author and review, as the platform does; an unknown sort is still refused with the full list
- `business_analytics_management`: profit margins print as percents ("-14,768.87%" instead of a bare "-14,768.8719" that read as dollars), and a 0 margin says it may mean the customer has no revenue, since the platform reports 0 for both no revenue and break-even. Top movers print the change as a percent and the previous and current costs as dollars, and task performance prints its durations in ms.
- `business_analytics_management`: skill costs, the PR-health cost per merged pull request, and the get_pr_health_follow_through at-risk estimates and cost bases print in USD with thousands separators, and amounts under a cent keep two significant digits instead of printing as 0. The at-risk and wasted estimates get_pr_health computes from the cost per merged pull request are unchanged.
- `manage_subscriptions`: search_subscriptions and discover_products take free text in search_query, search_subscriptions takes product_name, get_supporting_data takes data_type (all, organizations, products, subscribers or credentials; any other value is refused with that list) and subscription_nlp takes its query, instead of refusing each one as "not a recognized parameter"; get_capabilities lists these inputs
- `manage_subscriptions`: get_examples with example_type returns only that template (monthly_billing, trial_period, annual_billing or enterprise_custom) and refuses an unknown name with the valid ones, instead of refusing the input or answering with every template
- `manage_subscriptions`: create_with_credentials is no longer offered. It could never run, and it would have written a subscription and then a key with no preview and no rollback; create the subscription, then the key with `manage_subscriber_credentials` create and subscriptionIds
- `manage_subscriptions`: a create preview (dry_run, with or without auto_generate) and validate refuse an invoice address (clientEmailAddress) that the live create refuses, and the preview shows the trimmed address the create would send
- `manage_subscriptions`: update refuses a status field, which the platform does not store, instead of answering success while nothing changed, and the hint for a missing subscription_data lists only fields the platform update takes (name, expiration, clientEmailAddress, productId)
- `manage_products`: create_with_subscription takes subscription_data and creates the product and its subscription in one call; it requires the subscription's organizationId instead of attaching it to whichever organization is listed first, refuses before writing anything when a check fails, and names the product it left behind if the subscription itself is refused. Its answer names the organization billed and the subscriber's email, and says the platform created a user for that email. create_simple takes pricing_model, monthly_price, per_unit_price, setup_fee and setup_fee_type, refuses a price that is not a finite number of zero or more, refuses a per_unit_price (only a usage-based plan uses one) and a setup_fee_type without a setup_fee instead of dropping them, and refuses a usage-based quick create before writing anything because it cannot choose a metering element. clarify_pricing reads its text and suggest_template its requirements. Pricing and subscription inputs sent to an action that ignores them are refused instead of producing a free plan
- `manage_products`: create_simple and create_with_subscription have no preview, so a dry_run on either is refused with the error flag before anything is sent, instead of creating the product, its subscription and a platform user and answering as a success. The refusal points to create with dry_run, or get_templates, to preview a product
- `manage_products`: the "create subscribers" next step printed after a product create is a call the customers tool accepts, and it creates a subscriber in the organization it names instead of being refused or creating an organization
- `manage_products`: a create preview (dry_run) from a description, a name alone or product data builds the product with the same steps as the real create and shows what would be sent; a preview the real create would refuse is now an error instead of a result. A description that asks for per-use billing, such as "billed per call", names no metering element, so the preview and the real create both leave usage billing out and say so instead of the preview passing and the platform refusing the create
- `manage_products`: create_with_subscription refuses when the organization has no metering element instead of using an element id from another organization, and create_simple stores monthly_price as the plan's flat monthly fee instead of a per-unit price
- `manage_alerts`: alerts written as detection rules (create with detection_rules) or as plain text (create_from_text) are sent only with metric and window names the platform accepts. tokens_per_minute and requests_per_minute work, and "token rate" or "request rate" in plain text reads as the per-minute metric. Per-second metrics are refused with the per-minute metric to use, windows the platform lacks (such as 2h, 4h or 8h) are refused with an answer that names the accepted windows (15m, 30m, 1h, 12h, 24h, 1d, 7d, 30d), and windows under 15 minutes are refused with the 15-minute rule. 24h and 1d become DAILY, 7d becomes WEEKLY and 30d becomes THIRTY_DAYS; the platform refuses the TWENTY_FOUR_HOURS and SEVEN_DAYS names its contract lists. A threshold rule with no window is checked every 15 minutes instead of a 5-minute window the platform refuses, and a dry run refuses what the live create would refuse
- `/rm-alert-per-transaction`: creates a cost-per-transaction alert with the threshold given, checked every 15 minutes and sent to the default email, instead of being refused for an operatorType argument the tool does not take
- `manage_alerts`: the capabilities, examples and error hints no longer suggest `create_threshold_alert` with period_minutes 5 or 10, which the action refuses; they use 15, except one basic real-time monitoring example that still shows period_minutes 5 for now
- `manage_products`, `manage_sources` and `manage_subscriptions`: on the hosted server, creating a product, source or subscription, and editing a product, no longer fail with "ownerId is a required field". New records are owned by the signed-in caller unless the request names an owner, and an edited product keeps the owner it had
- Hosted server with a server-wide REVENIUM_API_KEY in its environment: each signed-in customer's new products, sources and subscriptions are owned by that customer, an alert created without an email notifies the customer's own address, and the setup and diagnostics tools show the customer's own team and email, instead of the key owner's. Starting in api_key or clerk mode with REVENIUM_API_KEY set logs a warning that names the risk, and `.env.example` leaves the key commented out with a note on when it applies
- `slack_management` and `manage_alerts`: on the hosted server, a default Slack configuration chosen with set_default_configuration or select_default_configuration applies to the organization that chose it only, until the server restarts. Another customer is no longer told it is their default, and their new alerts created without a Slack id no longer carry it. A local server still remembers its default for new alerts as before
- `manage_subscriptions`: search_subscriptions by subscriber_email or customer_name finds the subscriptions the platform's own search finds, over all subscriptions rather than one page, and reports the platform's total in total_found (null when the platform gives none) with the rows on the page in returned, which replaces original_total; each row carries matched_on, and two search terms together are refused instead of answering 0
- `manage_subscriptions`: a create with only a name asks which product to use, listing up to five, and is marked as an error, instead of answering "Could not auto-generate product_id" as plain text
- `manage_subscriptions`: the unsupported create_simple and create_from_text shortcuts are no longer advertised in the supported actions, capabilities or usage hints
- `manage_customers` and `manage_sources`: a list says how many of the platform's total are on the page ("Found 20 of 500 users (page 1 of 25)") instead of reporting the rows on the page as the number found; when the platform reports no total, or the page is past the last, the heading says so. A page given as text (page "1") no longer crashes the customer list. The JSON adds page and total_records; total_found is unchanged
- `manage_customers`: a 403 from delete_department_person or clear_department_assignment names both causes (department attribution not enabled, or the key not allowed to change departments) and how list_departments tells them apart, instead of always blaming the feature flag and calling it not a permissions problem
- `manage_customers`: the get_relationships action is removed. It never read the platform and answered the same placeholder for any id, real or invented; calling it now returns the standard unknown-action error, and it is no longer advertised in the action list, quick start or capabilities
- `manage_customers`: get_roles shows a new user created with ROLE_API_CONSUMER and lists that role first; the organization administrator role stays listed with its permissions, but no get_roles example grants it
- `business_analytics_management`: get_tool_costs, get_top_tools, get_tool_costs_by_agent and get_tool_costs_by_provider read the period asked for instead of the last 24 hours, and take start_date/end_date like the other cost actions; each answer names the exact start and end the platform was asked for (BACK-4624)
- `manage_tools`: the tool analytics actions read the start_date/end_date range or period asked for instead of the last 24 hours, send tool_id to get_cost_breakdown and provider to get_cost_by_provider under the names the platform reads, and refuse a filter their report does not take (agent, tool_name, granularity, group, or tool_id/provider on any other action) instead of ignoring it; each answer names the window it read (BACK-4625)
- `business_analytics_management` and `manage_tools`: the tool cost reads cover the whole window instead of its first 20 time buckets, so a day's tool spend by provider is no longer a third of the real figure; a read that would need more than 20 pages of 100 rows says it stopped there; a `manage_tools` read with no window reads every page for the same last 24 hours and names them (BACK-4640)
- `manage_metering`: lookup_transactions and lookup_recent_transactions in full detail show a duration, time to first token or tokens per minute of 0 (a non-streamed call has a time to first token of 0) instead of hiding it, and keep the Performance Metrics block when all three are 0
- `manage_metering`: lookup_transactions searches every id of a batch together, once per round with one pause between rounds, instead of one id at a time, so checking 20 just-submitted ids with max_retries 3 waits 30 seconds instead of 10 minutes. A call takes at most 50 ids (more are refused; duplicates are searched once), 10 rounds (max_retries), 60 seconds between rounds (retry_interval), 10 pages (search_page_range, now 10 by default instead of 50; the platform filters by id, so the first page normally holds the match), a page_size of 100 and 300 seconds of waiting in all; a value above a limit is lowered and the answer names it in an Adjusted line, and a value that is not a whole number is refused
- `manage_metering`: lookup_transactions waits for wait_seconds, which it used to ignore: sending it turns polling on and sets the most seconds the lookup spends waiting between searches (0 to 300), and sent alone it also sets how many searches fit in it
- `manage_metering`: lookup_transactions answers a platform error, refused access (403) or timeout as an error that names the failure for each id, says when a search was incomplete, and lists what was still found, instead of saying the transaction was not found. A search that completed and found nothing still answers Not Found
- `manage_metering` `submit_ai_transaction`: a transaction sent with its request_time but no response_time is recorded as finishing request_time plus duration_ms after it started, and its completion start as request_time plus time_to_first_token, instead of both being the time of the call; given response and completion-start times are kept, and a transaction sent with no timestamps is still recorded as now
- `manage_metering` `submit_ai_transaction`: reasoning_tokens, cache_creation_tokens and cache_read_tokens are accepted as arguments, listed in the parameters, field documentation and an Anthropic example, and checked like output_tokens (0 or more), so a prompt-cached call is metered with its cache and reasoning tokens instead of 0
- `manage_metering` `submit_ai_transaction`: a dry run refuses a transaction_id the real submit refuses, with the same message, instead of answering ready for submission
- `manage_metering`: the scope note, the include_coding_assistants description and the lookup help say false excludes coding assistants billed as seat subscriptions while assistants your team pays API rates for (apiRateProviders) stay in the results, instead of saying false excludes every coding assistant; a lookup by transaction id or trace id (lookup_transactions, or a transaction_id or trace_id filter) says include_coding_assistants has no effect on it, because the platform returns the record either way
- `manage_metering`: the parameter descriptions get_capabilities lists give the ranges the lookup applies: page_size 1 to 100 with a default of 100, and max_retries, retry_interval and wait_seconds their own ranges, each saying a value outside it is moved to the nearest limit. The bounds kept inside the tool's own schema no longer claim a page_size ceiling of 1000 and match these limits; no caller is shown or checked against them
- `manage_metering_elements`: get_capabilities names the three shipping templates get_templates holds, and get_agent_summary states their count, instead of advertising API-call, storage and compute templates and "6+" or "4" templates
- `manage_metering` validate: a transaction_id the submit refuses (such as `my-run-1`, an empty string or `tx_short`) and the deprecated `organization_id` and `product_id` are refused with the same error the submit gives, instead of answering Validation Successful
- `manage_metering`: lookup_transactions and lookup_recent_transactions in full detail show the reasoning-token count a submit stores as Reasoning Tokens; a count of 0 shows as 0 and a transaction without one shows no line
- `manage_metering`: a lookup_transactions page_size above 100 is now lowered to 100 with a notice because the platform serves at most 100 rows a page, and the default page is 100; the lookup help, field documentation and examples say 1-100 and up to 1,000 transactions per lookup instead of promising 1,000 per page and 10,000 per lookup, and get_api_endpoints and lookup_recent_transactions state a maximum of 100 instead of 50
- `manage_metering`: the lookup help and get_examples no longer offer a "Deep Historical" lookup_transactions example with search_page_range [20, 29], which answered Not Found for a transaction that exists because the lookup filters by id on the server and the match is on the first page; the widest example now searches pages 0 to 9, and the help says a range that starts past page 0 skips the match
- `manage_metering`, `manage_metering_elements`, `manage_alerts`, `manage_customers`, `manage_sources` and the other list actions: a page or size that is a whole number but out of range (such as size 101, or "101") is answered with the accepted range and, for a size above 100, how to request the next page, instead of advice to send it as an integer or a digit-only string
- `manage_jobs`: list_jobs, get_conversion_funnel and get_roi_summary take startDate and endDate as yyyy-MM-dd days, which cover the whole UTC day, or as ISO 8601 times with Z or an offset, instead of answering "Invalid date format" (list_jobs, get_conversion_funnel) or stopping at the start of the end day (get_roi_summary). An empty one is treated as not given; anything else, a time without Z or an offset included, or a start after the end is refused naming both forms. get_roi_summary's filters_applied shows the UTC instants it sent, and a refused summary carries the platform's message
- `manage_jobs`: get_roi_summary's heading names the window the platform answered for and says when it is the platform's default window, or when the platform chose the start or the end; get_conversion_funnel's heading names the dates sent or says no date window was applied, and its result reports filters_applied
- `manage_jobs`: get_job, get_job_transactions, get_job_roi, report_outcome and amend_outcome send the job id as one encoded path segment, as append_outcome_metrics already did, so an id with "/", "#" or "?" never reads or writes another job. A job id of "." or ".." is refused on all six job-id actions, and get_job refuses "types" and "conversion-funnel", whose bare path is another endpoint
- `manage_metering` `submit_ai_transaction`: on the hosted server, a transaction sent without a region, environment or other tracing field is no longer filled from the hosted server's own settings, such as its cloud region. A local server still fills them from its environment variables
- `manage_products`, `manage_metering_elements` and `manage_subscriber_credentials`: a list page past the last no longer says "No items found" with the advice to check permissions. It says the page is past the last, how many items and pages the list has, and the page and size to ask for the last or the only page. Every next and previous page hint in these lists also carries the page size, so following it no longer skips rows when the size is not 20
- `manage_subscriber_credentials`: list and list_by_organization show the page that was returned instead of always page 1, so the header and the next page hint move on as the pages do
- `slack_management`: list_configurations hints for the next and previous page carry the page size the call asked for
- `business_analytics_management` `get_coverage_ratio`: start_date and end_date alone read that calendar range and the header names the days read, instead of answering for the last 30 days; a named period sent with dates is refused, as on the other cost reports
- `get_seat_utilization`: a requested day the seat census did not return is named, instead of being left out of the list without a word
- `get_skill`: a not-found answer says the id may not be one of the team's skills and points to list_skills, and suggests only periods wider than the one used
- Every tool except `business_analytics_management`: a wrong action name now answers with an error that lists every action the tool offers, and a missing argument shows the handler's usage example and suggestions, instead of a one-line "Unknown action" or "Required parameter is missing". `system_setup`, `system_diagnostics` and `slack_management` answer an unknown action as an error instead of a normal result. `manage_subscriptions` cancel and `manage_metering_elements` assign_to_source keep their own explanation and are no longer coded as unknown actions
- `manage_ai_insights`, `tool_introspection`, `manage_capabilities` and `manage_metering`: a missing AI-insights run, an unknown tool name, an unsupported capability resource type and an AI-model search with no search term are answered as errors instead of normal results; the resource type refusal names the real cause instead of advising a connectivity check. A platform failure on an AI-model read is an error too, only a 400 or 422 is called a validation error, and the platform's raw response body is never shown

- `manage_ai_insights`: yes/no values given as text inside params (slim on get_run, the two filters on trigger_run) are read as true or false, so get_run returns the full run for slim "false" and names the setting it used; other text is refused
- `manage_ai_insights`: list_runs since and until take a yyyy-MM-dd UTC day (until covers the whole day) or an ISO 8601 time (no zone means UTC), so runs made on the until day are included; unreadable bounds or a since after until are refused
- `business_analytics_management`: analyze_cost_anomalies states a spike's size as its cost divided by normal, so a day at $86.31 against a normal of $22.56 reads 3.8x normal cost levels instead of 2.8x; the Cost multiplier and the sentence agree, and the table's percent column, now headed "% vs Normal", is measured against the same normal (the middle of the normal range)
- `business_analytics_management`: analyze_cost_anomalies names a dimension whose report failed or timed out as "not read" with the reason, instead of counting it as 0 entities with no anomalies; when no report could be read the answer is "Cost Anomaly Analysis Failed" with each reason, not "Total anomalies detected: 0", and the reports are read at most three at a time instead of one after another
- `business_analytics_management`: analyze_cost_anomalies describes a cost well below the average as "standard deviations below the average" instead of "above", and an all-weekend pattern as a "Weekend anomaly pattern"
- `business_analytics_management`: analyze_cost_anomalies on the analytics API (REVENIUM_USE_NEW_ANALYTICS_API=true) reads every page of each report, so SEVEN_DAYS examines all of its six-hour buckets instead of the first 20; a read that stops at the page cap says which part of the window was not examined. The legacy route is read as before
- `business_analytics_management`: analyze_cost_anomalies with detect_new_entities reports a provider, agent or API key that has cost in the recent part of the window and none (new) or little (activated) in the baseline, with the date it was first active and how many recent buckets it was active in, for every period including TWELVE_MONTHS. The baseline is a share of the buckets the platform returned instead of a day count, the answer names the recent and baseline spans, says when nothing new appeared, and says why when detection could not run
- `business_analytics_management`: analyze_cost_anomalies over HOUR, EIGHT_HOURS or TWENTY_FOUR_HOURS with detect_new_entities reads seven days of data for the detection, as its notice now says with the span it read, instead of saying the period was widened to SEVEN_DAYS while comparing the short window's first hourly points; the anomalies keep the requested window, and a seven-day read that fails is named with its reason
- Self-hosted HTTP server: the server refuses to start over HTTP (container, compose, or `TRANSPORT_MODE=http` from source) when AUTH_MODE is not set, instead of answering every caller with no sign-in and acting with the server's own REVENIUM_API_KEY. The error names AUTH_MODE and its three modes, and under compose `docker compose logs mcp-server` shows it while the container restarts. This deliberately breaks self-hosted HTTP setups that never set AUTH_MODE: set AUTH_MODE=api_key to require each caller's own key, AUTH_MODE=clerk for OAuth sign-in, or AUTH_MODE=env to keep the open server on a trusted network, which now logs a warning naming the opt-in. If your `.env` was copied from an earlier `.env.example`, it already contains `AUTH_MODE=env`, which now counts as the deliberate opt-in: change it to `AUTH_MODE=api_key` unless you mean to run without sign-in. `.env.example` no longer sets AUTH_MODE. Local stdio use is unchanged
- `business_analytics_management`: get_coverage_ratio with period custom takes start_date and end_date as yyyy-MM-dd calendar days, each covering the whole UTC day with both days included, as well as ISO-8601 instants with Z or an offset, instead of failing with "Invalid date format" on a calendar date. A value in neither form, or a start after the end, is refused with both accepted forms named
- `business_analytics_management`: get_coverage_ratio names each provider row by its label (for example Anthropic Console or Claude Enterprise), falling back to the provider code, lists its billing credential names, and tells a row with no billing credential to connect its key in Revenium's Manage Connections. It describes a row's ratio as Revenium-metered spend divided by billed spend, not a share of billed spend, and says the aggregate counts only providers with a billing credential; get_capabilities describes the row ratio the same way
- `business_analytics_management`: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs, get_agent_costs and get_cost_summary answer a start_date/end_date range on deployments that do not set REVENIUM_USE_NEW_ANALYTICS_API, such as the hosted server, instead of refusing it. A range is read from the analytics API whenever the report has a route there; a named period still takes the route it took before
- `business_analytics_management`: get_user_costs returns every user instead of the first 20. It reads 100 users per page by default, takes page and size (1 to 100), says which page of how many it is and how many users the report holds, gives the call for the next page, and labels its totals as the page's own when the report has more than one page
- `business_analytics_management`: get_team_costs returns the whole requested window instead of its first 20 days, and the other analytics-pack reads (task costs and completion, task performance, profit margins, top movers, token breakdown, vendor costs, token vs tool cost) read every page of rows the platform has instead of the first 20; a read that would need more than 20 pages of 100 rows says it stopped there. The daily series print one line per day with every team or task side by side, so a month for several teams, or a year, is no longer cut at 50 lines
- `business_analytics_management`: get_provider_costs, get_model_costs, get_customer_costs, get_api_key_costs and get_agent_costs add up the whole start_date/end_date range instead of its first 20 days, so September 1 to 30 no longer answers the September 1 to 20 total
- `business_analytics_management`: get_coverage_ratio explains an n/a aggregate on a VALID report instead of a generic "no provider billing" guess. It names the compared providers (billing credential connected and overlapping the window) that billed nothing in it, since the platform publishes the aggregate only when every compared provider billed something, and shows metered divided by billed across the compared providers as a labelled diagnostic that is not the coverage ratio
- `business_analytics_management`: get_coverage_ratio with a provider that answers NO_INTEGRATION says that the platform matches only a billing credential of exactly that provider, so a Claude Enterprise connection is not found by provider=ANTHROPIC, and that the call without provider shows the vendor's row
- `business_analytics_management` and `manage_customers`: the cost-source notes state the platform's rule. A call's cost source is where its row came from (a stored cost source, otherwise coding_assistant for a coding-assistant call, otherwise revenium_metered; provider_billing rows come from invoices), and a team's API-rate setting decides whether coding-assistant calls are counted at all, not which source they are under. Claude Enterprise coding-assistant usage the team pays API rates for is therefore under coding_assistant, valued at API rates, and a revenium_metered plus provider_billing request can legitimately return nothing; the earlier notes said such usage was real spend under revenium_metered or provider_billing
- `manage_subscriber_credentials` and every other write: when the platform refuses a write, the server's error log records no longer hold the secrets from the request body (externalSecret, access tokens, passwords, API keys); they are masked whichever logging setup is active, including where the platform echoes one back in its error message, and the error the tool returns carries the same masked text
- Every tool: a call with an argument the tool does not accept, or one of the wrong type, no longer writes that argument's value into the server log, so a misplaced credential secret stays out of it. The hosted sign-in proxy refuses a self-signed identity-assertion token it was never configured to accept, and revokes the right token when a refresh token is revoked (fastmcp 4.0.10)
- `system_diagnostics` and `system_setup`: system_health, onboarding_status, show_welcome, setup_checklist and the other setup checks say HEALTHY, READY, "API connectivity is working", "Your setup looks good" or that setup is complete only after a read of the organization's data made with the caller's own key or sign-in succeeds, in every sign-in mode. A hosted sign-in no longer reads HEALTHY while the platform is unreachable, a hosted key that works is no longer told it is not configured, and hosted answers no longer list checks of the server's own settings and cache
- `system_setup`: help and get_actions tell the assistant to call `system_setup(action=...)`, the tool it can see, instead of `welcome_and_setup`, which the server does not register
- `system_setup`: complete_setup with confirm_completion true finishes, confirming that the caller can read the organization's data, instead of always answering "Setup Completion Error" with an internal message and debug lines. When the read fails the answer is an error that names the next step, and nothing is written to the server's cache file
- `system_diagnostics`, `system_setup` and `slack_management`: an organization is called a first-time user only when the platform shows neither ingested data nor a Slack configuration for it. An organization with data is no longer told it has none, one with Slack configurations is no longer offered Slack setup, the answer is the same on a hosted and a local server, and a cache file left by another caller no longer changes it; when the platform cannot be read the answer says the status is unknown
- `manage_alerts`: create_threshold_alert keeps isPercentage and every address in notificationAddresses, together with email and without duplicates, instead of storing a plain count sent to one person; email may be one address or a list, and anything else is refused under email; the confirmation lists every stored recipient and marks a percentage threshold. create_cumulative_usage_alert, create_simple and create_from_text (a number followed by %) follow the same rule, and an argument a quick action cannot apply, such as period or filters on create_threshold_alert, is refused with nothing created
- `manage_alerts`: update applies a flat email (together with any notificationAddresses) and a flat period instead of answering "Updated Successfully" with the old recipient and check frequency kept. A period the alert type cannot take, such as weekly on a threshold alert, is refused with nothing updated; an email sent alone is an update rather than a missing-argument answer; a missing anomaly_id or nothing to change now carries the error flag; and an update is reported as an error naming any field it was given, filters and triggerAfterPersistsDuration included, that the stored alert does not show, reading the alert back when the platform's answer leaves the field out; slack_config_id, period_minutes and filters given as flat arguments are applied and checked like the rest, and any other flat argument, such as tags, which alerts do not have, is refused with nothing updated instead of being accepted and dropped, and a malformed email is refused under email rather than notificationAddresses
- `manage_alerts`: enable_all, disable_all, clear_all and get_status cover every alert instead of the first page (the platform returns at most 100 a page), and their totals are the platform's own. An action that stops before reaching every alert says how many it covered out of how many exist and is worded as partial, not complete
- `manage_subscriptions`, `manage_customers`, `manage_sources`, `manage_products` and `manage_metering_elements`: an update stores every field the caller sends, except a fixed set of read-only fields that an update always drops whoever sends them. Moving a subscription to another product, moving a subscriber to another organization, setting an organization's parent, and changing a source's tags, external id or usage plan used to answer "updated successfully" while the stored value stayed the same. Fields the caller leaves out, such as an organization's parent on a name-only update, are kept as before
- `manage_products`: an update that sends part of a plan, such as only its charge, keeps every plan field it leaves out (tiers, period, elements, setup fees) instead of replacing the stored plan and deleting its pricing tiers while answering "updated successfully". A tiers list that is sent replaces the stored one, and an update that would leave the plan with no tiers is refused with the error flag set, as create refuses it
- `manage_workflows`: on the hosted server a started workflow is visible and changeable only by the organization that started it. Another customer's list no longer shows it, and their get, next_step and complete_step on its id answer not found and change nothing
- `manage_metering`: on the hosted server lookup_transactions and get_transaction_status answer only from transactions the asking organization submitted. A lookup of an id another customer submitted no longer returns that customer's record (subscriber email included); it asks the platform under the caller's own key. The server remembers at most the last 1,000 submissions instead of every one until restart
- `manage_subscriptions`: cancel no longer deletes the subscription. The platform has no cancel operation, so cancel is refused with an error that leaves the record untouched, says delete permanently removes the record, and names update with an expiration date as the only non-destructive route the API exposes, which the server cannot confirm stops billing; get_capabilities and the examples no longer offer cancel, and the delete answer says the record was permanently removed
- `manage_subscriptions` and `manage_customers`: get_metrics and analyze report only figures the platform data supports, instead of 0 active records and 0% rates. Subscription states (active, trial, expired, not started) come from each subscription's start, expiration and trial end dates, products are counted from the subscription's product, and organizations and teams with a parent count as hierarchical. Every rate is the share of the records read, and the answer says which page it covers out of how many records, or that coverage is unknown when the platform reports no total. Conversion, churn, billing-period and customer activity figures are no longer reported because the platform returns nothing to compute them from. get_metrics reads 100 subscriptions per page by default
- `manage_metering_elements`: assign_to_source is no longer offered. It answered "Elements assigned to source successfully" without saving anything, because the platform has no operation that assigns elements to a source; calling it now returns an error that nothing was assigned and that elements are linked through `manage_sources` with `meteringElementDefinitionIds` in source_data. That list replaces the source's links, so the help says to read the source first and send the IDs in its `meteringElementDefinitions[].id` together with the new ones. The help no longer points to it or to get_source_elements, which never existed
- `manage_jobs`: get_job_transactions lists the transactions the platform holds for the job and reports the platform's total_count, instead of always answering an empty list with 0 items. The action is not paged, so it refuses a page or size other than the defaults and no longer prints a page, size or page count the platform never sent; a job with no calls still answers an empty list with total_count 0, and a platform answer without a transactions list is reported as an error instead of an empty list
- README: the Claude Code setup that installs the server into a Python virtual environment now registers `python -m revenium_mcp_server`, the module the package installs, for both the starter and business profiles, instead of `python -m revenium_mcp`, which does not exist and left Claude Code showing the server as failed at launch
- `tool_introspection` get_tool_metadata, and the tool metadata JSON behind it: on the hosted server they say per-tool performance metrics are not shown there, instead of printing execution counts, success rate and response time that added up every organization's calls since the server started. A server run with its own key keeps showing them
- `system_diagnostics`: search_logs with a status, operation or search filter gives the matches on the page it fetched and labels the platform's total and page count as unfiltered, instead of printing the unfiltered total as Total Entries under the filter
- `system_diagnostics`: search_logs with search_all_pages says how many pages and entries it searched out of the platform's total and calls itself complete only when it read every page; when it stops at a failed page, at its page limit or at an empty page it says so and why, instead of always claiming the complete historical dataset
- `system_diagnostics`: analyze_operations and get_recent_logs report the pages they actually read, not the pages asked for, and say which page failed when one stopped them early
- `manage_products` and `manage_subscriber_credentials`: get_subscriptions, get_related_credentials, get_subscription_details and get_product_details refuse to answer from a partial subscription list: the error says which subscriptions page failed to load and that the list is incomplete, and ends with "Retry the request", instead of answering from the pages read before it; a credential lookup no longer says no subscription uses the credential when a page failed
- `/health`: reports the platform's state under `platform`, in every auth mode: the HTTP status code the platform root answered to a keyless HEAD and when, how old that is, and timeout or unreachable when there was no answer. 2xx to 4xx mean the platform is up and 5xx means its gateway is not serving. An operator can now see a platform outage such as a 502 or 503 while `/health` stays 200 and never waits on the network; a stale state is refreshed in the background at most once per readiness cache period, and that refresh never sends an API key. `/ready` keeps answering for the server itself, and the README now says what it checks in each auth mode
- `manage_metering`: lookup_transactions, lookup_recent_transactions and analyze_recent_transactions no longer ask the platform for a seat-plan list it does not have before answering, so the server log no longer carries a "defaulting to allow-all" warning on every lookup. The records shown are the platform's answer for the chosen include_coding_assistants view, unchanged.
- `manage_subscriber_credentials`: resolve_subscriber_email_to_id finds any subscriber by email through the platform's lookup instead of only the first 100, and resolve_organization_name_to_id searches every page of matching organizations instead of the first 100. An email or name that matches nobody is an error, an organization name that two organizations share, or that the search cannot confirm is unique, is refused and asks for organizationId, and a failed lookup is reported as a failure instead of "not found". Create, dry run included, refuses a subscriber_email or organization_name that is empty, matches nobody or cannot be looked up, instead of failing on a missing subscriberId or previewing a credential with no subscriber
- `manage_customers`: get with resource_type users or subscribers and an email finds people who exist, through the platform's lookup-by-email, instead of always answering not found
- `manage_ai_insights` `list_runs`: when the analytics service refuses a value such as `status` or `triggered_by`, the error names each refused field, the value received and the accepted values, instead of only "Invalid input". `manage_jobs` `get_roi_summary` still reports only "request failed (status=400)" and is a follow-up
- `manage_alerts`: alert history windows count back from the moment the question is asked, not from when the server started, so "the last hour" on a server that has run for days includes the alerts that fired this hour, and the 30-day default for an undated question ends now
- `manage_alerts`: "this week", "today", "this month", "from 2026-10-12 to 2026-10-14" and "from Oct 12 to Oct 14" answer instead of "Failed to list alerts"; a to-date includes that whole day, "yesterday" is the previous UTC day, any "last N minutes, hours, days or weeks" covers that span, "since" ends now, explicit filters start and end are sent in the platform's form, a start after the end is refused, and every answer states its window in UTC, saying when no date range was recognized and the last 30 days were read
- `manage_alerts`: with no resource_type, query reads alert history and echoes the question whatever it asks (pass resource_type anomalies to query the alert rules), and list routes by the question, sending fired, recent or historical questions to alert history and other lists to the rules; resource_type is no longer defaulted to anomalies before routing, get, create, update, delete and clear_all still default to anomalies, and query honours page and size
- `manage_alerts`: alert values print in full, with a dollar sign for cost metrics ("Triggered Value: $1,023.49" against "Condition: > $1,000.00") instead of "1.0K", and count metrics print every digit
- `manage_alerts`: a number and a unit choose the alert history window only after "last", "past" or "previous", or before "ago", so "alerts that fired yesterday for rules with a 15 minute period" reads yesterday, not the last 15 minutes. In "from Oct 12 to Oct 18" with no year, the end takes the start's year, or the next year when it falls before the start, so the range is no longer refused as backwards. Alert values below one millionth keep their first two significant digits instead of printing "$0.00" or "0"
- `slack_management`: detect_and_recommend and select_default_configuration print each channel name exactly as Slack sends it, so a channel reads "#clerk-dev" instead of "##clerk-dev" and a direct message "@name" instead of "#@name", and the recommendations show each configuration's real creation date instead of "Unknown"
- `slack_management`: the next steps after choosing a default, and the setup_status, onboarding_setup and first_time_guidance examples, name alert actions that exist (create_cumulative_usage_alert, create_simple) and offer the checklist as system_setup(action='setup_checklist')
- `slack_management`: get_configuration, set_default_configuration, get_default_configuration and select_default_configuration with an id that is not one of the organization's Slack configurations say the configuration was not found or is not in your organization instead of "HTTP 403: Access Denied"; other errors are unchanged
- `system_setup`: test_configuration with a malformed configured email says the format is not valid and notifications are not ready, and how to fix the address, instead of summarizing it as valid and ready
- `system_setup`: update_email returns an error saying the email was not saved when it could not be stored, instead of "Successfully configured"; on the hosted server it is refused because the server has nowhere to keep an address for the organization, and an address can be given on each alert instead
- `manage_sources`: create and validate keep every field the caller gives, such as tags, externalId and externalUsagePlanId, when auto_generate is on (the default), instead of replacing them with a payload built from name, description, version and type with empty tags. Auto-generation fills only the fields left empty; teamId and ownerId are still filled by the server
- `manage_products`: a plan's setup fees are stored whether they are spelled setup_fees or setupFees, instead of being dropped when spelled setup_fees; when both spellings are given, the setupFees entries come first, followed by the setup_fees entries
- `manage_sources`: create and validate accept top-level name, type, description, version and url the same way as inside source_data, instead of refusing a top-level name as missing; a source_data value wins when both are given. get_capabilities and get_examples say so instead of saying creation fields must be nested in source_data
- `manage_sources`: the usage example attached to the create_from_text error for missing text names create_from_text(text=...) instead of create_from_description, which does not exist. The example is in the error's structured details, which MCP clients do not receive; the message they see, Required parameter 'text' is missing, is unchanged
- `manage_metering`: lookup_recent_transactions, analyze_recent_transactions and submit_ai_transaction take every filter and trace field get_capabilities lists (start_date, end_date, the cost, duration, token and latency ranges, subscriber_id, environment, region, retry_number, usage_metadata and the rest) as top-level arguments, instead of refusing them as "not a recognized parameter" and accepting them only inside params. Integer ranges such as request_duration_min stay integers on the wire. The help no longer lists recent_page_size with a note disowning it, and a page-size error names page_size
- `manage_subscriber_credentials`: get_troubleshooting_guide, parse_natural_language, get_business_guidance, get_onboarding_checklist, analyze_billing_impact and get_examples take the input each one asks for (issue_description, text, scenario, customer_info, operation, example_type), and create takes the individual fields its error describes (label, externalId, externalSecret, tags, subscriptionIds), instead of refusing them at the boundary. The troubleshooting guide answers once it has an issue description instead of failing with a serialisation error
- `manage_subscriber_credentials`: the validate hint for an update shows validate(credential_id=..., credential_data={...}) instead of an operation_type argument the tool refuses
- `manage_subscriber_credentials`: a create preview (dry_run) looks the subscriber up and fails the preview when the platform does not know it, as the real create would; a subscriber it cannot verify is a warning. When an external ID is given, the preview warns that it cannot check for an existing credential with that external ID, because the platform masks external IDs, and that a create with an existing external ID returns the existing credential
- `manage_metering` `get_integration_capabilities`: the Python example runs as pasted, with no import from the server's own package
- `manage_metering` `list_ai_models` and `search_ai_models`: no longer suggest a get_ai_model action that does not exist
- `manage_metering` `lookup_transactions`, `lookup_recent_transactions` and `analyze_recent_transactions`: with include_coding_assistants=false, the scope line names the coding-assistant records the platform returned (priced at API rates) instead of saying they were excluded
- `manage_metering_elements`: hints name only real templates, and a create_from_template dry run refuses an unknown or missing template the way the real create does
- `manage_metering` `get_integration_guide` for javascript: names `@revenium/middleware`, with its install command and the REVENIUM_METERING_API_KEY and REVENIUM_METERING_BASE_URL variables it reads
- `business_analytics_management`: aggregated cost reports (get_task_costs with aggregation=aggregated, and get_vendor_costs) list each task or vendor once with its cost and run count labelled, ranked by cost, and count what was left out; the other aggregated lists say they show the first 50 in the platform's order instead of claiming a top
- `business_analytics_management`: get_merged_prs lists one line per person, busiest first, with empty days left out, so a daily month for a team is no longer cut at 200 lines, and pages the people with people_offset
- `business_analytics_management`: over-time reports leave out entries at zero and say so; a day where everything was zero reads "nothing above zero", and values under a cent still print as $0.00
- `business_analytics_management`: list_invoices and list_refunds print every row of the page asked for, up to 100, instead of stopping at 50 with rows 51 to 100 out of reach, and end with the page number, the total and the page and size to pass for the next page; a page past the last names the total instead of saying none were found. list_period_charges also prints every row of its page
- `business_analytics_management`: list_refunds shows each refund's amount with its currency, when it was issued, when it was applied to an invoice, and its product, instead of "n/a | n/a" on every line, and no longer prints a state column the refund does not have
- `business_analytics_management`: list_period_charges shows each charge's amount with its currency, the call count, the type and charge type, the product and the transaction id once, instead of only ids and a timestamp. Billing amounts print two decimals, and a charge under one cent keeps its digits rather than printing as zero
- `manage_tools`: update and replace change only the fields you pass. The tool's name, id and type are read from the stored tool and sent with your change, so renaming a tool or changing only its description no longer fails with "toolId is a required field", its pricing is left alone, and a disabled tool is no longer switched back on by an update (BACK-4696)
- `manage_products`, `manage_sources`, `manage_alerts` and `manage_jobs`: list actions accept page sizes up to 100, the most rows the platform returns in one page, instead of refusing anything over 50 as "Maximum page size is 50 items" (on alert lists, as "Failed to list alerts" with advice to check the connection). A size over 100 is refused with a message naming 100
- `manage_products`: create leaves a new product unpublished and with no data source unless the request sets `published` or `sourceIds` (or `source_ids`), and create_simple always makes an unpublished draft with no data source, instead of publishing it and attaching the organization's first source. The answer says on its first line whether the product is published and which data sources it has, suggests subscriptions only for a published product with a source, and otherwise gives the update that publishes it and attaches one. A `source_ids` list is no longer replaced by the organization's first source (`sourceIds` wins when both are given), a usage-based product created with no source is refused before anything is created with a hint to pick one from manage_sources(action='list'), and an update no longer publishes a product whose stored record does not say whether it is published. create_with_subscription still attaches a source and publishes the product so it can take the subscription, unless the request sets `published` to false, and its answer now says whether the product was published. manage_subscriptions refusals of an unpublished product now say a data source is needed as well as publication
- `manage_customers` and `manage_sources`: an update that changes an organization's, team's or source's metadata stores it, instead of answering "updated successfully" with the old metadata kept. Metadata is sent only when the update includes it, so other edits leave the stored metadata alone. It must be a string of name=value pairs separated by commas; any other value, which the platform would drop without an error or use to clear an organization's metadata, is refused with nothing sent, and metadata sent to a record that has none, such as a subscriber or a product, is refused instead of ignored
- `manage_customers`: updating a subscriber who has no first or last name, for example changing only their phone number, no longer names them "Unknown User"; the names the subscriber has, or the update sets, are sent as they are. Subscribers already renamed this way keep that name
- `manage_sources`: update changes a source that has no description instead of refusing with "Required fields missing after merge: description", and no longer sends an asset usage identifier of API_ENDPOINT or an empty code, plan id or source type that neither the source nor the caller had. A source with no owner, when no REVENIUM_OWNER_ID is configured, is refused naming ownerId before anything is sent, since the platform requires an owner and a team
- `manage_products`: update with dry_run reads the product and shows the exact body the update would send, instead of answering "Would update product" for any id. A preview of a product that does not exist, or of a plan change that would remove every pricing tier, fails with the error flag as the update does, and nothing is sent
- `manage_customers`: an organization created without a parentId is top-level instead of nested under the caller's team; an explicit parentId still nests it
- `manage_customers`: a subscriber created without organizationIds is refused with a message that names the field and the list action for finding organization ids, instead of being attached to the first listed organization
- `manage_customers`: a user or subscriber created without an email is refused with a message saying an email is required, not a JSON format error, and the resource_data description no longer promises an email generated from a name
- `manage_customers`: the create preview (dry_run) refuses what the real create refuses, subscribers get no invented last name, and a user whose lastName cannot be derived from the email is refused instead of stored with the last name "Name"
- `manage_alerts` validate: checks an alert the way create does and answers valid or gives create's reason for refusing it, instead of always answering "Alert validation unavailable". validate without an alert is an error with the error flag set. A create (or validate) whose detection_rules convert to a check period under 15 minutes, including a THRESHOLD rule without time_window, is refused before anything is sent, as the platform would refuse it. The 15-minute floor applies to every alert type, budget alerts included, a budget alert takes only DAILY, WEEKLY, MONTHLY or QUARTERLY and its refusal names those, and TWENTY_FOUR_HOURS, which the platform does not recognise as a period, is refused with DAILY as the fix
- `manage_alerts` update with dry_run: the preview runs the real update's checks against the stored alert and answers what the update would answer, including direct arguments such as threshold, and sends nothing. An update that changes the period or alert type now refuses check periods under 15 minutes, budget periods other than DAILY, WEEKLY, MONTHLY or QUARTERLY, and TWENTY_FOUR_HOURS, as create does; period_minutes 1440 updates the alert to DAILY, as create_threshold_alert does, instead of a period the platform does not recognise
- `manage_alerts`: examples, hints and the parameter reference name only check intervals of 15 minutes or longer, and document the real default of 15 minutes
- `manage_alerts`: error suggestions name real actions and arguments (`validate(anomaly_data=...)`, `create_simple`, `get_status`, `slack_management(action="list_configurations")`)
- `manage_alerts` create, validate, update and the update preview: a check period is accepted only if the platform keeps it for that alert type and data source, so they refuse what the platform would refuse before anything is sent. A budget alert takes DAILY, WEEKLY, MONTHLY or QUARTERLY; an alert with dataSource PROVIDER takes DAILY, WEEKLY or MONTHLY; every other alert takes FIFTEEN_MINUTES to QUARTERLY or THIRTY_DAYS. A detection_rules time_window of 1d is sent as DAILY, and 2h, 4h or 8h, which have no platform period, are refused with the windows the alert takes; lower-case and unknown periods such as daily or ONE_DAY are refused on update as they are on create. Period refusals suggest only periods create accepts. A RELATIVE_CHANGE alert with dataSource PROVIDER is refused, because a provider-sourced alert takes THRESHOLD or CUMULATIVE_USAGE only, and a dataSource other than exactly SDK or PROVIDER, such as provider, is refused naming the two values. A provider alert on a metric other than TOTAL_COST, TOKEN_COUNT, INPUT_TOKEN_COUNT or OUTPUT_TOKEN_COUNT, or filtered on a dimension other than WORKSPACE, API_KEY, MODEL or PROVIDER, is refused as the platform refuses it, and a null dataSource is accepted: on create the platform stores it as SDK, and on update it keeps the stored data source, so the update, its preview and the after-write check all read the stored one. Create, validate, the update and its preview now check one table of every rule the platform enforces on an alert that needs no live data: alert type, data source, metric name, operator by alert type, period, filter rows (no DEPARTMENT, at most 50 IN values), groupBy, triggerAfterPersistsDuration (none on RELATIVE_CHANGE), threshold (a finite number, or a string in plain number form such as 12.5; NaN, Infinity and 1_000 are refused, and an update sends a threshold string as a number, as create does), QUALITY_RATE, and the provider rules; a metric the platform does not have, such as TOKENS_PER_SECOND, is refused. An update checks the whole alert, as the platform does: renaming an alert whose stored period or operator is no longer accepted is refused, naming the stored value and the values to send in the same update
- `manage_alerts`: an alert or anomaly that does not exist, a missing or blank required argument, a refusal raised by the alert or anomaly manager, and a refused notification setting now come back marked as errors with the same guidance text, so a client that checks the error flag no longer reads them as success; a platform server error while reading an alert's history is named a server error with its HTTP status instead of "not found". Dry-run verdicts and confirmation previews still come back as results
- `manage_alerts`: an alert history list whose start is after its end now comes back marked as an error, with the same "Window refused" text
- `manage_alerts`: validate and a create with dry_run that refuse an alert now come back marked as errors with the live create's text, so a refused preview carries the error flag like the refused create
- `manage_subscriptions`, `manage_agents`, `manage_tools` and `manage_cost_controls`: a list says how many of the platform's total are on the page ("Found 20 of 500 agents (page 1 of 25)") instead of reporting the rows on the page as the number found; when the platform reports no total, or the page is past the last, the heading says so. The JSON adds total_records (and page on subscriptions); total_found is unchanged
- List arguments such as `tags`, `transaction_ids`, `email_addresses` or `providers` refuse the word null and a quoted string instead of handing on the text itself; a single value that starts with [, { or a quote goes inside an array, as in `["[beta] tag"]`, and the refusal now says so; a bare number or true/false is a plain value, sent as typed. `manage_customers` refuses `user_data`, `organization_data`, `subscriber_data` and `team_data` on actions other than create, update and validate, and `manage_metering_elements` refuses `overrides` outside create_from_template, instead of ignoring them; the refusal names the argument and the actions that read it, never its contents. `manage_tools` `tool_data`, `event_data` and `filters`, and `manage_customers` `resource_data`, must be JSON objects, as on `manage_agents` and `manage_cost_controls`, so `filters='[]'` is refused instead of reading as no filter
- `manage_alerts` update: a flat `period` of weekly, monthly, thirty_days or quarterly is applied to a threshold or relative-change alert, the same windows `periodDuration` takes on that alert, instead of being refused as not valid for the alert type; budget and provider alerts keep their own lists
- `manage_alerts` create and validate: a detection rule whose `time_window` is empty, blank or null gets the default a rule without one gets, instead of being refused for a window nobody sent: 15 minutes, or for a budget or relative-change rule the alert's own period (daily when none is given)
- `manage_alerts` create_simple: a dry run refuses what the live create refuses (such as TOKENS_PER_SECOND, a metric the platform does not have), with the error flag and the same text, instead of answering "Dry Run Successful"; a preview that passes shows the body the create would send
- `manage_alerts`: the capability metric groups, the alert schema and the natural-language examples no longer offer TOKENS_PER_SECOND or REQUESTS_PER_SECOND, which the platform does not measure; the examples name per-minute throughput, and the daily API calls example, which was refused, is replaced by a daily token usage example the tool creates
- `manage_alerts` create, validate, update and their previews: a threshold written with a bare decimal point, such as ".5" or "5.", is accepted and sent as the number 0.5 or 5.0 instead of being refused as not a number
- `manage_alerts` create, validate and update: a filter row whose `value` is an empty string is accepted and sent as the platform stores it; a row with no value at all is still refused, and a QUALITY_RATE job-type filter still needs a job type name
- `manage_alerts` update: renaming or otherwise editing a cost or token alert that already stores a `minSampleCount` updates it instead of refusing the stored value; setting a new value off QUALITY_RATE, and a create that sets one, are still refused because the platform stores it there and never reads it
- `manage_alerts` create actions and update: a Slack configuration id the organization does not have is named in the refusal ("Slack configuration ... was not found in this organization; nothing was created"), with a pointer to `slack_management` list_configurations, instead of being reported as an invalid alert id; an update that sends no Slack id keeps the platform's own refusal, even when the alert stores a Slack id the organization no longer has
- `manage_customers` and `manage_sources` update: metadata refused because a piece is not one name=value pair now names that piece (for example `ClaudeCowork` in `providers=ClaudeCode,ClaudeCowork`) and says the platform would answer success but drop it, because a comma always ends a value
- `manage_products` update and its preview: an update sends the product's own team instead of the team the server is configured with, so a product in one team of a multi-team organization is no longer moved; a caller's `teamId` or `team` still wins
- `manage_metering_elements` update: an update sends the team the platform stores on the element when it returns one, and otherwise the team the server is configured with. The platform returns no team on an element today, so updates still send the configured team, and an element that later carries its own team keeps it
- `manage_sources` and `manage_metering_elements` update with dry_run: the preview reads the record, refuses an id that does not exist the way get does, and shows the body the update would send, instead of approving any id and echoing the changes
- `manage_products` create_with_subscription: an organization id the platform does not know is refused before anything is written, so a wrong id no longer leaves a stray product behind; a key that cannot read organizations still creates as before
- `manage_customers`: the help no longer lists a `relationships` resource type, describes users as people who sign in to Revenium instead of platform admins, describes the administrator role the way get_roles does, and shows subscriber update examples with a field a subscriber has (`firstName`)

## [0.8.0] - 2026-10-08

### Added
- `business_analytics_management`: get_department_costs reports cost, requests and tokens per department for the whole period, with the same period, aggregation and filters as get_user_costs. Each department shows its own figures and, labelled apart, the figures with its sub-departments; spend from people with no department is its own group; a team with no departments, no assignments or no loaded data is told so rather than shown $0. Department ids in the answer are hashids, not the numeric ids list_departments returns
- `business_analytics_management`: four PR-health reads (get_pr_health_breakdown, get_pr_health_queue, get_pr_health_trend, get_pr_health_follow_through) show where the figures come from per repository, engineer or department, the open pull requests that need a decision grouped by cause, the at-risk and closed-without-merge trend per day, week or month, and whether the pull requests flagged as rotting got fixed; the existing PR-health lists can search by login, filter by cause, repository, ticket and triage state, and list the automation pull requests
- `business_analytics_management`: get_ai_assistant_team_medians reads the anonymous team medians of Claude Code habits (context per call, cache rebuild ratio, share of requests above default effort); with fewer than five people the platform withholds them and the answer says so
- `business_analytics_management`: get_seat_utilization reports whether the latest Claude Enterprise sync read the seat census (READ, UNREAD, UNKNOWN); get_coverage_ratio renders an incomplete coding-assistant check as unknown and names each provider's revision window
- `manage_alerts`: alert authors can look up a provider API key by name or id (search_provider_api_keys) and a provider alert keeps its dataSource on create so it can carry an API_KEY filter; alert reads show whether the alert is firing right now
- `manage_customers`: the PR-health digest can be read and changed (get_pr_health_digest_settings / update_pr_health_digest_settings): the weekly digest and rotting alert switches, day, hour, timezone, Slack channels and email addresses, sending only the fields named; previewing and test-sending the digest stay in the app
- `manage_customers`: get_coding_assistant_billing_settings reads which coding assistants a team pays for at real API rates and which pricing modes someone has confirmed; changing them stays in the app
- `manage_cost_controls`: get_budget_portfolio accepts group_limit and a grouped budget shows the group that will trip its alert; control_data documents notificationEmails, the addresses that receive a control's warn and block notices, including the update rule that an empty list clears them while omitting the field leaves them unchanged
- `manage_metering`: transaction details render clientSurface and the field analysis counts it
- `system_diagnostics`: get_ingestion_failures shows each rejection's error code and resolution and can be narrowed with error_code

### Changed
- `system_diagnostics`: set_usage_billing says what switching usage billing off does on the platform now: besides hiding the billing screens it stops rating the tenant's usage, and usage that arrives while it is off is never rated later; get_usage_billing is described the same way
- Analytics, AI Insights, jobs ROI, PR-health, merged-PR and budget-portfolio reads send the team the session resolved, so a user who belongs to several teams no longer gets the figures of a different team
- Upstream contract snapshots and generated models refreshed through 2026-10-08

### Fixed
- `business_analytics_management`: get_user_costs and get_department_costs ask for every cost source (coding_assistant, revenium_metered, provider_billing) when the caller passes none. The two-source default answered an empty report on tenants whose spend is coding-assistant usage reported under coding_assistant; which source carries a tenant's spend is tenant-dependent, so the notes no longer claim that any one source returns no rows. An explicit filters.costSources subset is still sent as given
- `business_analytics_management`: hosted connectors return cost per user (get_user_costs) instead of answering that the report needs the new analytics API, and get_capabilities lists the action again
- `business_analytics_management`: a get_department_costs page past the last one is told apart from an empty report, and MEAN, MAXIMUM and MINIMUM keep fractional request and token figures
- `manage_ai_insights`: trigger_run no longer offers or sends filter_include_coding_assistants_for_cost_detectors, which the platform ignores (the cost checks follow the team's coding-assistant pricing policy); passed as a top-level argument it is rejected with an unknown-argument error. filter_include_coding_assistants is unchanged
- `manage_cost_controls`: enforcement-event rows are described with their tier (the line the event crossed), and level is no longer called the tier that fired, which was wrong when a non-blocking rule crosses its cap
- `manage_alerts`: an exhausted provider-key search page points back at the pages that hold the matches

## [0.7.1] - 2026-09-28

### Changed
- Org units are now departments, following the platform rename: `manage_customers` lists them with list_departments and removes memberships with delete_department_person / clear_department_assignment; `manage_cost_controls` previews a parent's children with preview_department_group and takes DEPARTMENT as the group-by and filter dimension; PR Health in `business_analytics_management` and analysis runs in `manage_ai_insights` are scoped with department_id / filter_department_id. The org-unit names (list_org_units, delete_org_unit_person, clear_org_unit_assignment, preview_org_unit_group, org_unit_id, parent_org_unit_id, filter_org_unit_id, ORG_UNIT) are still accepted for this release, flagged deprecated on the advertised schemas, and will be removed in the next one
- Upstream contract snapshots and generated models refreshed through 2026-09-28

### Fixed
- Every org-unit read and write answered 404 after the platform renamed its endpoints on 2026-09-27; the tools now call the department endpoints, and the compiled-rule warnings summary in `manage_cost_controls` reads the department budget keys the platform now returns

## [0.7.0] - 2026-09-24

### Added
- `manage_metering`: transactions can be submitted with prompt id, prompt length, query source, speed mode and subagent type; the full-detail lookup renders them in a Prompt Context block, and also shows the agentic job name, type and version and the trace grouping fields (trace type, transaction name, parent transaction)
- `business_analytics_management`: PR Health can be scoped to one org unit (optionally with its descendants) and shows the cutoff date, excluded repositories and AI-assisted, merged and automation totals it applied; four drill-downs (get_pr_health_engineers, get_pr_health_prs, get_pr_health_pull_requests, get_pr_health_repositories) page every engineer, open one engineer's pull requests, list the bucketed pull requests and the repositories covered; get_merged_prs counts merged pull requests per person or per repository
- `manage_customers`: PR-health settings read and write repository exclusions, automation patterns, the assisted-only default and the cutoff date, with a warning when the platform stores something other than what was sent; org-unit memberships can be removed (delete_org_unit_person, clear_org_unit_assignment) behind an explicit confirm
- `system_diagnostics`: tenant admins can read and change whether billing screens are shown (get_usage_billing / set_usage_billing)
- `manage_cost_controls`: enforcement events can be narrowed by rule, level, mode and window, with summary, history and affected-subscriber reads; one compiled rule and the roster of who it covers can be read
- `manage_jobs`: job type economics, baselines and period facts; the job-type ROI row carries modalityCost with the four-way cost split
- `manage_alerts`: alert reads say whether the count includes activity recorded before the rule existed

### Changed
- Tool schemas advertised on connect are ~3x smaller (18.7K -> 6.0K tokens for the 20-tool business profile): nullable unions are collapsed to the type callers actually send, and the five heaviest tools (`manage_metering`, `business_analytics_management`, `manage_alerts`, `manage_ai_insights`, `manage_tools`) now advertise `action`, their paging/filter parameters and a `params` object. Existing calls are unaffected — every named argument these tools accepted before is still accepted, at the top level or inside `params`; a top-level argument wins over the same name inside `params`, and `params` wins over the tool's default
- `get_capabilities` on those five tools now ends with a reference for every parameter the advertised schema no longer lists: name, type, accepted values and meaning, generated from each tool's own schema declaration
- `manage_ai_insights`: realized_savings carries its type and meaning in the get_capabilities parameter reference
- Upstream contract snapshots and generated models refreshed through 2026-09-24

### Fixed
- `manage_jobs`: a job type containing a dot segment no longer collapses the request path; a malformed JSON argument is refused instead of silently ignored; the economics write discloses its lost-update window
- `manage_metering`: the submit-then-read-back field comparison checks the prompt-context fields under the names the platform stores

## [0.6.0] - 2026-09-10

### Added
- `manage_jobs`: amend a reported outcome (amend_outcome) under the platform's optimistic lock; a stale expected entity version is refused and the current version is named. Outcome guidance documents the metrics array and entityVersion
- `manage_jobs`: read session ticket attributions (list_session_attributions), including the reason a session was classified as it was
- `manage_jobs`: get_roi_summary reads the platform's published ROI summary instead of stitching funnels client-side
- `manage_metering`: analyze_recent_transactions reports field coverage across recent transactions; transaction detail renders cache creation/read tokens and session-stored transactions
- `manage_metering`: AI model listings show the price-pin flag and distinguish an empty catalog from a malformed envelope
- `manage_alerts`: IN filter operator with a values list; QUALITY_RATE metric with its prerequisites (declared job type, TASK_TYPE filter, minSampleCount); operators advertised and validated per alert type, EQUAL_TO/NOT_EQUAL_TO refused on create and update with guidance
- `manage_agents`: description (max 1024 chars) and metadata (max 8192 bytes) on create and update
- `manage_cost_controls`: several values in one filter row; department-budget warnings summarized
- `manage_customers`: create-time platform warnings called out above the created resource; org-unit warnings summarized
- `manage_subscriber_credentials`: read an organization's credentials
- `system_diagnostics`: attribution-detail-text toggle
- tools/list advertises cache hints (ttlMs / cacheScope) so clients stop re-fetching it

### Changed
- fastmcp 3.4.7 -> 4.0.0, mcp 1.29.0 -> 2.1.1 (MCP protocol revision 2026-07-28; the best mutual protocol era is negotiated per connection, so older clients are unaffected); pydantic >= 2.12
- Upstream API contract pinned: models generated from committed OpenAPI snapshots, with a drift alarm in tests
- Readiness verdicts (system_diagnostics, system_setup, manage_capabilities) require a successful authenticated read; a forbidden read is reported as NOT READY with neutral wording instead of counting as connectivity, and a rejected key is named as such on the setup path
- Analytics empty results no longer assert user inactivity; the cost summary states its coding-assistant scope
- `manage_jobs`: job filter enum values are validated locally with the platform's case handling and PENDING contract; upstream 400 bodies are no longer echoed
- `manage_tools`: tool_version is no longer advertised (the platform discards it) and is rejected when present; tool categories derive from the contract
- `manage_alerts`: an unknown-id 403 is translated to a named not-found
- Validation and unknown-action refusals are raised as tool errors instead of returned as text

### Fixed
- A validation error raised inside a tool handler is reported as a tool error again instead of a JSON-RPC "Invalid request parameters"
- `manage_metering`: the documented submit fields are accepted; an unknown model name is not reported as an API outage; get_supported_providers reports the real model total; dry-run and validate share the catalog check
- `manage_subscriptions`: clientEmailAddress must be an email address on every creation path
- `system_setup`: checklists stamped with real UTC; the Slack app URL resolves from the configured environment; dev users are no longer told to set REVENIUM_APP_BASE_URL
- Coverage-ratio responses say what is and is not compared

### Removed
- `manage_tools`: the restore action, which the platform never supported

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

[0.8.1]: https://github.com/revenium/revenium-mcp/releases/tag/v0.8.1
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

[0.8.0]: https://github.com/revenium/revenium-mcp/releases/tag/v0.8.0
[0.7.1]: https://github.com/revenium/revenium-mcp/releases/tag/v0.7.1
[0.7.0]: https://github.com/revenium/revenium-mcp/releases/tag/v0.7.0
[0.6.0]: https://github.com/revenium/revenium-mcp/releases/tag/v0.6.0
[0.5.0]: https://github.com/revenium/revenium-mcp/releases/tag/v0.5.0
