# Ask Revenium to create a per-transaction cost alert. Usage: `/rm-alert-per-transaction [threshold]`. Default: $5

Create an alert when any transaction cost exceeds a threshold from Revenium.

**Usage:** `/rm-alert-per-transaction [threshold]`
- Example: `/rm-alert-per-transaction 5` to alert when any transaction exceeds $5
- If no threshold provided, defaults to $5

Use the manage_alerts tool with these parameters:
- action: "create_threshold_alert"
- name: "Transaction Cost Alert - $[threshold]"
- threshold: [threshold from user input, default 5]
- metricType: "COST_PER_TRANSACTION"
- operatorType: "GREATER_THAN"
- periodDuration: "FIVE_MINUTES"

## Use Case
Immediate alert when any single transaction exceeds the threshold amount. Early warning for unexpected high-cost transactions.

## Optional: Reduce Alert Noise
If the user wants less frequent alerts, add:
- triggerAfterPersistsDuration: "FIVE_MINUTES"

## Deliverables
Confirm the alert was created and provide details of the configuration.
