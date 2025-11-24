"""Subscriber Object Migration Validation and Management.

This module provides enhanced migration validation and timeline management
for subscriber object backward compatibility, complementing the existing
comprehensive NLP support.

Following development best practices:
- Validation of migration accuracy
- Formal deprecation timeline management
- Optional automatic conversion with user consent
- Migration tracking and analytics
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


class SubscriberMigrationValidator:
    """Validates subscriber object migrations and ensures data integrity."""

    def __init__(self):
        """Initialize the migration validator."""
        self.old_field_mappings = {
            "subscriber_email": "subscriber.email",
            "subscriber_id": "subscriber.id",
            "subscriber_credential": "subscriber.credential.value",
            "subscriber_credential_name": "subscriber.credential.name",
        }

    def convert_old_to_new_format(
        self, old_data: Dict[str, Any], remove_old_fields: bool = True
    ) -> Dict[str, Any]:
        """Convert old subscriber format to new format.

        Args:
            old_data: Data in old format with individual subscriber fields
            remove_old_fields: Whether to remove old fields after conversion

        Returns:
            Data converted to new subscriber object format
        """
        new_data = old_data.copy()
        subscriber_obj = {}

        # Convert individual fields to subscriber object
        if "subscriber_email" in new_data:
            subscriber_obj["email"] = new_data["subscriber_email"]
            if remove_old_fields:
                new_data.pop("subscriber_email")

        if "subscriber_id" in new_data:
            subscriber_obj["id"] = new_data["subscriber_id"]
            if remove_old_fields:
                new_data.pop("subscriber_id")

        # Handle credential fields
        credential = {}
        if "subscriber_credential" in new_data:
            credential["value"] = new_data["subscriber_credential"]
            if remove_old_fields:
                new_data.pop("subscriber_credential")

        if "subscriber_credential_name" in new_data:
            credential["name"] = new_data["subscriber_credential_name"]
            if remove_old_fields:
                new_data.pop("subscriber_credential_name")

        if credential:
            subscriber_obj["credential"] = credential

        # Add subscriber object if any fields were converted
        if subscriber_obj:
            new_data["subscriber"] = subscriber_obj

        return new_data

    def validate_migration(
        self, old_data: Dict[str, Any], new_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate that migration preserves data integrity.

        Args:
            old_data: Original data in old format
            new_data: Data in new format (either converted or provided)

        Returns:
            Validation results with detailed feedback
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "field_mappings": [],
            "data_integrity": True,
        }

        # Convert old format for comparison
        converted_data = self.convert_old_to_new_format(old_data.copy())

        # Validate field mappings
        for old_field, new_path in self.old_field_mappings.items():
            if old_field in old_data:
                old_value = old_data[old_field]
                new_value = self._get_nested_value(new_data, new_path)

                if new_value is None:
                    validation_result["valid"] = False
                    validation_result["errors"].append(
                        {
                            "field": old_field,
                            "error": f"Field '{old_field}' not found in new format at '{new_path}'",
                            "old_value": old_value,
                            "suggestion": f"Ensure '{new_path}' is set to '{old_value}'",
                        }
                    )
                elif str(old_value) != str(new_value):
                    validation_result["valid"] = False
                    validation_result["errors"].append(
                        {
                            "field": old_field,
                            "error": f"Value mismatch: '{old_value}' != '{new_value}'",
                            "old_value": old_value,
                            "new_value": new_value,
                            "suggestion": f"Update '{new_path}' to match original value",
                        }
                    )
                else:
                    validation_result["field_mappings"].append(
                        {
                            "old_field": old_field,
                            "new_path": new_path,
                            "value": old_value,
                            "status": "valid",
                        }
                    )

        # Check for data integrity
        if not self._validate_data_integrity(converted_data, new_data):
            validation_result["data_integrity"] = False
            validation_result["warnings"].append(
                {
                    "type": "data_integrity",
                    "message": "Converted data differs from provided new format",
                    "suggestion": "Review conversion logic and ensure all fields are properly mapped",
                }
            )

        return validation_result

    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get value from nested dictionary using dot notation path."""
        keys = path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def _validate_data_integrity(self, converted: Dict[str, Any], provided: Dict[str, Any]) -> bool:
        """Validate that converted data matches provided data."""
        # Compare subscriber objects if both exist
        converted_subscriber = converted.get("subscriber", {})
        provided_subscriber = provided.get("subscriber", {})

        if not converted_subscriber and not provided_subscriber:
            return True

        # Check key fields match
        key_fields = ["id", "email"]
        for field in key_fields:
            converted_value = converted_subscriber.get(field)
            provided_value = provided_subscriber.get(field)

            if converted_value and provided_value:
                if str(converted_value) != str(provided_value):
                    return False

        return True


class DeprecationManager:
    """Manages deprecation timeline and warnings for subscriber object migration."""

    def __init__(self):
        """Initialize deprecation manager with timeline."""
        # Set deprecation timeline (6 months total)
        self.timeline = {
            "warning_start": "2025-06-17",
            "deprecation_start": "2025-09-17",
            "sunset_date": "2025-12-17",
        }

        self.phases = {
            "warning": "Old format still supported but deprecated",
            "deprecation": "Old format deprecated, migration strongly recommended",
            "sunset": "Old format no longer supported",
        }

    def get_current_phase(self, current_date: Optional[str] = None) -> str:
        """Get current deprecation phase.

        Args:
            current_date: Current date in YYYY-MM-DD format (defaults to today)

        Returns:
            Current phase: 'warning', 'deprecation', or 'sunset'
        """
        if current_date is None:
            current_date = datetime.now().strftime("%Y-%m-%d")

        current = datetime.strptime(current_date, "%Y-%m-%d")
        warning_start = datetime.strptime(self.timeline["warning_start"], "%Y-%m-%d")
        deprecation_start = datetime.strptime(self.timeline["deprecation_start"], "%Y-%m-%d")
        sunset_date = datetime.strptime(self.timeline["sunset_date"], "%Y-%m-%d")

        if current >= sunset_date:
            return "sunset"
        elif current >= deprecation_start:
            return "deprecation"
        elif current >= warning_start:
            return "warning"
        else:
            return "active"

    def get_deprecation_warning(self, current_date: Optional[str] = None) -> Dict[str, Any]:
        """Get appropriate deprecation warning based on current phase.

        Args:
            current_date: Current date in YYYY-MM-DD format

        Returns:
            Deprecation warning with timeline and severity
        """
        phase = self.get_current_phase(current_date)

        if phase == "active":
            return {"phase": "active", "warning": None}

        warning_data = {
            "phase": phase,
            "timeline": self.timeline,
            "description": self.phases[phase],
        }

        if phase == "warning":
            warning_data.update(
                {
                    "severity": "INFO",
                    "message": "⚠️ Subscriber format deprecation notice",
                    "details": "The individual subscriber fields format is deprecated. Please migrate to the new subscriber object format.",
                    "action_required": "Plan migration to new format",
                    "time_remaining": self._calculate_time_remaining(
                        current_date, "deprecation_start"
                    ),
                }
            )
        elif phase == "deprecation":
            warning_data.update(
                {
                    "severity": "WARNING",
                    "message": "🚨 Subscriber format deprecation active",
                    "details": "The individual subscriber fields format is deprecated and will be removed soon. Migration is strongly recommended.",
                    "action_required": "Migrate to new format immediately",
                    "time_remaining": self._calculate_time_remaining(current_date, "sunset_date"),
                }
            )
        elif phase == "sunset":
            warning_data.update(
                {
                    "severity": "ERROR",
                    "message": "❌ Subscriber format no longer supported",
                    "details": "The individual subscriber fields format is no longer supported. Use the new subscriber object format.",
                    "action_required": "Update to new format required",
                    "time_remaining": "0 days (sunset reached)",
                }
            )

        return warning_data

    def _calculate_time_remaining(self, current_date: Optional[str], target_phase: str) -> str:
        """Calculate time remaining until target phase."""
        current_date_str = current_date or datetime.now().strftime("%Y-%m-%d")
        current = datetime.strptime(current_date_str, "%Y-%m-%d")
        target = datetime.strptime(self.timeline[target_phase], "%Y-%m-%d")

        if current >= target:
            return "0 days"

        delta = target - current
        return f"{delta.days} days"


class MigrationTracker:
    """Tracks migration usage and provides analytics."""

    def __init__(self):
        """Initialize migration tracker."""
        self.migration_stats = {
            "old_format_usage": 0,
            "new_format_usage": 0,
            "migration_attempts": 0,
            "validation_failures": 0,
            "last_old_format_usage": None,
        }

    def record_format_usage(self, format_type: str, timestamp: Optional[str] = None):
        """Record usage of old or new format.

        Args:
            format_type: 'old' or 'new'
            timestamp: Usage timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        if format_type == "old":
            self.migration_stats["old_format_usage"] += 1
            self.migration_stats["last_old_format_usage"] = timestamp
        elif format_type == "new":
            self.migration_stats["new_format_usage"] += 1

    def record_migration_attempt(self, success: bool):
        """Record a migration attempt.

        Args:
            success: Whether the migration was successful
        """
        self.migration_stats["migration_attempts"] += 1
        if not success:
            self.migration_stats["validation_failures"] += 1

    def get_migration_analytics(self) -> Dict[str, Any]:
        """Get migration analytics and recommendations.

        Returns:
            Analytics data with usage patterns and recommendations
        """
        total_usage = (
            self.migration_stats["old_format_usage"] + self.migration_stats["new_format_usage"]
        )

        if total_usage == 0:
            return {"status": "no_usage", "recommendations": []}

        old_percentage = (self.migration_stats["old_format_usage"] / total_usage) * 100
        success_rate = 100

        if self.migration_stats["migration_attempts"] > 0:
            success_rate = (
                (
                    self.migration_stats["migration_attempts"]
                    - self.migration_stats["validation_failures"]
                )
                / self.migration_stats["migration_attempts"]
            ) * 100

        analytics = {
            "usage_statistics": self.migration_stats,
            "old_format_percentage": round(old_percentage, 2),
            "new_format_percentage": round(100 - old_percentage, 2),
            "migration_success_rate": round(success_rate, 2),
            "recommendations": self._generate_recommendations(old_percentage, success_rate),
        }

        return analytics

    def _generate_recommendations(self, old_percentage: float, success_rate: float) -> List[str]:
        """Generate recommendations based on usage patterns."""
        recommendations = []

        if old_percentage > 50:
            recommendations.append("High old format usage detected - prioritize migration efforts")

        if old_percentage > 0:
            recommendations.append(
                "Consider implementing automatic conversion for remaining old format usage"
            )

        if success_rate < 90:
            recommendations.append(
                "Migration validation failures detected - review migration logic"
            )

        if old_percentage == 0:
            recommendations.append("Excellent! All usage has migrated to new format")

        return recommendations


# Global instances for easy access
migration_validator = SubscriberMigrationValidator()
deprecation_manager = DeprecationManager()
migration_tracker = MigrationTracker()
