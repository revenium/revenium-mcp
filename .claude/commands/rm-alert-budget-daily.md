# Ask Revenium to create a daily budget alert. Usage: `/rm-alert-budget-daily [threshold]`. Default: $100

Create an alert when daily costs exceed a threshold from Revenium.

**Usage:** `/rm-alert-budget-daily [threshold]`
- Example: `/rm-alert-budget-daily 100` to alert when daily costs exceed $100
- If no threshold provided, defaults to $100

Use the manage_alerts tool with these parameters:
- action: "create_cumulative_usage_alert"
- name: "Daily Budget Alert - $[threshold]"
- threshold: [threshold from user input, default 100]
- period: "daily"

## Use Case
Daily budget monitoring, immediate alert when daily spending exceeds the threshold amount.

## Related
Once a budget alert has tripped, `manage_alerts` action `reset_budget`
(`reset_budget(anomaly_id="...")`) restarts the current period's accumulation
without waiting for the daily boundary to roll over.

## Deliverables
Confirm the alert was created and provide details of the configuration.
