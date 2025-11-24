# Ask Revenium to detect cost anomalies (last 24h). Usage: `/rm-anomalies-24h [threshold]`. Default: $50

Detect unusual cost patterns in the last 24 hours from Revenium using enhanced statistical analysis across all dimensions.

**Usage:** `/rm-anomalies-24h [threshold]`
- Example: `/rm-anomalies-24h 50` to detect anomalies over $50
- If no threshold provided, defaults to $50

Use the business_analytics_management tool with these parameters:
- action: "analyze_cost_anomalies"
- period: "TWENTY_FOUR_HOURS"
- min_impact_threshold: [threshold from user input, default 50]
- sensitivity: "normal"
- include_dimensions: ["providers", "models", "customers", "api_keys", "agents"]

## Use Case
Daily anomaly overview across all tracked dimensions with immediate cost spike detection and proactive budget management.

## Deliverables
Review the output and provide comprehensive overview of:
1. **Temporal Anomalies**: Cost spikes and unusual patterns
2. **Dimensional Analysis**: Which providers, models, or customers are affected
3. **Recommendations**: Suggested actions based on findings
