# Ask Revenium to detect cost anomalies (last 30 days). Usage: `/rm-anomalies-30d [threshold]`. Default: $50

Check for unexpected cost anomalies AND newly active cost sources in the last 30 days from Revenium using enhanced statistical analysis.

**Usage:** `/rm-anomalies-30d [threshold]`
- Example: `/rm-anomalies-30d 50` to detect anomalies over $50
- If no threshold provided, defaults to $50

Use the business_analytics_management tool with these parameters:
- action: "analyze_cost_anomalies"
- period: "THIRTY_DAYS"
- min_impact_threshold: [threshold from user input, default 50]
- sensitivity: "normal"
- detect_new_entities: true
- min_new_entity_threshold: [threshold from user input, default 50]
- include_dimensions: ["providers", "agents", "api_keys"]

## Use Case
Monthly anomaly review with new entity detection for comprehensive cost governance.

## Deliverables
Review the output and provide comprehensive overview of:
1. **Temporal Anomalies**: Monthly cost spikes and unusual patterns
2. **New Entity Detection**: Newly active cost sources with first active dates
3. **Correlations**: Relationships between anomalies and new entities
