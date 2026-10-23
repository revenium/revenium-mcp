# Ask Revenium to create a per-transaction cost alert. Usage: `/rm-alert-per-transaction [threshold]`. Default: $5

Create a Revenium alert for when cost per transaction exceeds the threshold, checked every 15 minutes.

**Usage:** `/rm-alert-per-transaction [threshold]`
- Example: `/rm-alert-per-transaction 5` to alert when cost per transaction exceeds $5, checked every 15 minutes
- If no threshold provided, defaults to $5

Call the manage_alerts tool with exactly these arguments, replacing 5 in both `name` and `threshold` with the user's threshold:

```json
{"action": "create_threshold_alert", "name": "Transaction Cost Alert - $5", "threshold": 5, "metricType": "COST_PER_TRANSACTION", "period_minutes": 15}
```

The alert fires when cost per transaction is greater than the threshold; `create_threshold_alert` always uses the GREATER_THAN operator, and notifies the default email (your own on the hosted server; locally, the address saved with `system_setup` `update_email`, then REVENIUM_DEFAULT_EMAIL) unless you add `"email"`.

## Use Case
Alert when cost per transaction exceeds the threshold amount, checked every 15 minutes. Early warning for unexpectedly expensive transactions.

## Optional: Reduce Alert Noise
If the user wants less frequent alerts, add this argument to the same call:
- `"triggerAfterPersistsDuration": "THIRTY_MINUTES"`

## Deliverables
Confirm the alert was created and provide details of the configuration.
