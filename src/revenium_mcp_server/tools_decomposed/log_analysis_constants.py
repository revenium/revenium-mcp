"""Constants and text templates for Revenium Log Analysis Tool.

This module contains all large text blocks extracted from the main tool
to comply with function length requirements.
"""

# Capabilities text template
CAPABILITIES_TEXT = """
# Revenium Log Analysis Capabilities

## Available Actions

1. **get_internal_logs** - ✅ **AVAILABLE**
   - Retrieve internal system logs for troubleshooting
   - Supports pagination, filtering, and diagnostic analysis

2. **get_integration_logs** - ✅ **AVAILABLE**
   - Retrieve integration logs for external service monitoring
   - May be empty depending on system configuration

3. **get_recent_logs** - ✅ **AVAILABLE**
   - Recent activity analysis across multiple pages
   - Configurable page depth for "recent" definition

4. **search_logs** - ✅ **AVAILABLE**
   - Advanced filtering with operation and status types
   - Client-side search of details field
   - Supports comprehensive search across all pages

5. **analyze_operations** - ✅ **AVAILABLE**
   - Operation pattern analysis and frequency reporting
   - Error pattern identification

6. **get_capabilities** - ✅ **AVAILABLE**
   - Shows current implementation status

7. **get_examples** - ✅ **AVAILABLE**
   - Shows usage examples for all available actions

## 🔧 Parameter Usage

**Common parameters for log retrieval actions:**
```json
{
  "action": "action_name",
  "page": 0,                    // Page number (default: 0)
  "size": 200,                  // Records per page (default: 200, max: 1000)
  "log_type": "internal",       // Log type: internal|integration|both
  "operation_filter": "AI_METRIC_PROCESSING",  // Filter by operation type
  "status_filter": "SUCCESS",   // Filter by status: SUCCESS|FAILURE|INFO|WARNING
  "search_term": "keyword",     // Search in details field
  "search_all_pages": true      // Search across all pages (default: false)
}
```

## Supported Values
- **Log Types**: internal, integration, both
- **Operation Types**: Dynamically determined by system (use partial matching like "AI_METRIC" or "EMAIL_DISPATCH")
- **Status Types**: SUCCESS, FAILURE, INFO, WARNING
- **Page Size**: 1-1000 records (default: 200)

## 🔍 Advanced Filtering Examples

**Find all failures:**
```json
{"action": "search_logs", "status_filter": "FAILURE"}
```

**Find AI metering issues:**
```json
{"action": "search_logs", "operation_filter": "AI_METRIC", "status_filter": "FAILURE"}
```

**Search for specific errors:**
```json
{"action": "search_logs", "search_term": "timeout", "status_filter": "FAILURE"}
```

**Recent activity analysis:**
```json
{"action": "get_recent_logs", "pages": 3}
```
"""

# Examples text template
EXAMPLES_TEXT = """
# Revenium Log Analysis Examples

### get_capabilities
```json
{
  "action": "get_capabilities"
}
```
**Purpose**: List supported actions and parameters.

### get_internal_logs
```json
{
  "action": "get_internal_logs",
  "page": 0,
  "size": 200
}
```
**Purpose**: Retrieve internal system logs (AI metering, email dispatch).

### get_integration_logs
```json
{
  "action": "get_integration_logs",
  "page": 0,
  "size": 50
}
```
**Purpose**: Retrieve integration logs (may be empty - this is expected).

### get_recent_logs
```json
{
  "action": "get_recent_logs",
  "pages": 2
}
```
**Purpose**: Get recent activity from first N pages (~400 most recent entries).

### search_logs - Filter by Status
```json
{
  "action": "search_logs",
  "status_filter": "FAILURE"
}
```
**Purpose**: Find all failed operations for troubleshooting.

### search_logs - Filter by Operation
```json
{
  "action": "search_logs",
  "operation_filter": "AI_METRIC_PROCESSING",
  "status_filter": "INFO"
}
```
**Purpose**: Find AI metering operations with INFO status.

### search_logs - Search Content
```json
{
  "action": "search_logs",
  "search_term": "timeout",
  "status_filter": "ERROR"
}
```
**Purpose**: Search for timeout-related errors in log details.

### search_logs - Combined Filters
```json
{
  "action": "search_logs",
  "operation_filter": "EMAIL_DISPATCH",
  "status_filter": "FAILURE",
  "search_term": "notification"
}
```
**Purpose**: Find failed email notification operations.

### search_logs - Comprehensive Search
```json
{
  "action": "search_logs",
  "search_term": "KpV3POwqy106CCr",
  "search_all_pages": true
}
```
**Purpose**: Search for specific terms across entire historical dataset.

### analyze_operations
```json
{
  "action": "analyze_operations",
  "log_type": "internal",
  "pages": 3
}
```
**Purpose**: Analyze operation patterns and frequencies across multiple pages.

## Operation Types
Operation types are dynamically determined by the system. Common patterns include:
- AI transaction processing operations
- Email dispatch operations
- System integration operations
- Authentication and authorization operations

## Status Types
- `SUCCESS` - Operation completed successfully
- `FAILURE` - Operation failed (investigate details)
- `INFO` - Informational status (e.g., new products/organizations)
- `WARNING` - Operation completed with warnings

## 🎯 Agent-Friendly Filter Patterns

**For error investigation:**
```json
{"action": "search_logs", "status_filter": "FAILURE"}
{"action": "search_logs", "status_filter": "WARNING"}
```

**For specific operation monitoring:**
```json
{"action": "search_logs", "operation_filter": "AI_METRIC"}
{"action": "search_logs", "operation_filter": "EMAIL_DISPATCH"}
```

**For content-based searches:**
```json
{"action": "search_logs", "search_term": "timeout"}
{"action": "search_logs", "search_term": "connection"}
{"action": "search_logs", "search_term": "authentication"}
```
"""

# Unsupported action template
UNSUPPORTED_ACTION_TEMPLATE = """
❌ **Action Not Supported**

**Requested Action**: {action}

**Available Actions:**
- get_capabilities (see supported features)
- get_examples (see working examples)
- get_internal_logs (internal system logs)
- get_integration_logs (integration logs)
- get_recent_logs (recent activity analysis)
- search_logs (advanced filtering)
- analyze_operations (operation pattern analysis)

Use `get_capabilities()` for current status.
"""

# Error messages
ERROR_MESSAGES = {
    "size_limit": "Page size cannot exceed 1000 records",
    "api_error": "Failed to retrieve {log_type} logs: {error}",
    "filtering_error": "Failed to apply filters: {error}",
    "formatting_error": "Failed to format response: {error}",
    "multi_page_error": "Failed to retrieve multiple pages: {error}",
}

# Suggestions
SUGGESTIONS = {
    "size_limit": ["Use size <= 1000", "Use pagination for larger datasets"],
    "api_connectivity": [
        "Check API connectivity",
        "Verify page and size parameters",
        "Try with smaller page size",
    ],
    "integration_logs": [
        "Check API connectivity",
        "Verify page and size parameters",
        "Note: Integration logs may be empty (this is expected)",
    ],
    "filtering": [
        "Check filter parameters",
        "Verify log entries format",
        "Try simpler filter criteria",
    ],
    "formatting": [
        "Check API response structure",
        "Verify log data format",
        "Try with smaller page size",
    ],
    "multi_page": ["Check page parameter", "Verify API connectivity", "Try with fewer pages"],
}

# Default values
DEFAULT_VALUES = {"size": 200, "sort": "created,desc", "page": 0, "pages": 1}

# API endpoints
LOG_ENDPOINTS = {
    "internal": "/profitstream/v2/api/logs/system/internal",
    "integration": "/profitstream/v2/api/logs/system/external",
}

# Valid parameter values
VALID_VALUES = {
    "log_types": ["internal", "integration", "both"],
    "status_types": ["SUCCESS", "FAILURE", "INFO", "ERROR", "WARNING"],
    "common_operations": [
        "AI_METRIC_PROCESSING",
        "EMAIL_DISPATCH_AI_ALERT_NOTIFICATION",
        "EMAIL_DISPATCH_INVOICE_NOTIFICATION",
        "EMAIL_DISPATCH_PRODUCT_KEY_DEACTIVATION_NOTIFICATION",
    ],
}
