"""Dry run functionality for subscriber credentials management.

This module provides comprehensive dry run capabilities for credential operations,
including validation, conflict detection, and billing impact analysis.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from ..client import ReveniumClient
from ..common.security_utils import obfuscate_sensitive_string


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    """Represents a validation issue found during dry run."""

    severity: ValidationSeverity
    field: str
    message: str
    suggestion: str
    business_impact: str


@dataclass
class BillingImpact:
    """Represents billing implications of credential changes."""

    affected_subscriptions: List[str]
    metering_impact: str
    cost_implications: str
    automation_risk: str
    recommendations: List[str]


@dataclass
class DryRunResult:
    """Result of dry run validation."""

    operation: str
    valid: bool
    validation_issues: List[ValidationIssue]
    billing_impact: BillingImpact
    preview_data: Dict[str, Any]
    confidence_score: float
    next_steps: List[str]


class CredentialDryRunValidator:
    """Comprehensive dry run validator for credential operations."""

    def __init__(self, client: ReveniumClient):
        """Initialize the dry run validator."""
        self.client = client
        self._initialize_validation_rules()

    def _initialize_validation_rules(self):
        """Initialize validation rules and business constraints."""
        self.validation_rules = {
            "required_fields": {
                "create": [
                    "label",
                    "subscriberId",
                    "organizationId",
                    "externalId",
                    "externalSecret",
                ],
                "update": ["label", "externalId"],  # Minimum required for updates
            },
            "field_constraints": {
                "label": {"min_length": 3, "max_length": 100},
                "externalId": {"min_length": 3, "max_length": 255, "unique": True},
                "externalSecret": {"min_length": 8, "max_length": 512},
                "tags": {"max_count": 10, "max_length_per_tag": 50},
            },
            "business_rules": {
                "billing_critical_fields": ["subscriberId", "organizationId", "subscriptionIds"],
                "security_sensitive_fields": ["externalSecret"],
                "immutable_fields": [
                    "subscriberId",
                    "organizationId",
                ],  # Cannot be changed after creation
            },
        }

    async def validate_create_operation(self, credential_data: Dict[str, Any]) -> DryRunResult:
        """Validate credential creation operation."""
        logger.info("Performing dry run validation for credential creation")

        validation_issues = []
        preview_data = credential_data.copy()

        # Validate required fields
        validation_issues.extend(await self._validate_required_fields("create", credential_data))

        # Validate field constraints
        validation_issues.extend(await self._validate_field_constraints(credential_data))

        # Check for conflicts
        validation_issues.extend(await self._check_create_conflicts(credential_data))

        # Validate business relationships
        validation_issues.extend(await self._validate_business_relationships(credential_data))

        # Analyze billing impact
        billing_impact = await self._analyze_billing_impact("create", credential_data)

        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(validation_issues)

        # Generate next steps
        next_steps = self._generate_next_steps("create", validation_issues, billing_impact)

        return DryRunResult(
            operation="create",
            valid=not any(
                issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
                for issue in validation_issues
            ),
            validation_issues=validation_issues,
            billing_impact=billing_impact,
            preview_data=preview_data,
            confidence_score=confidence_score,
            next_steps=next_steps,
        )

    async def validate_update_operation(
        self, credential_id: str, credential_data: Dict[str, Any]
    ) -> DryRunResult:
        """Validate credential update operation."""
        logger.info(f"Performing dry run validation for credential update: {credential_id}")

        validation_issues = []

        # Get current credential data
        try:
            current_credential = await self.client.get_credential_by_id(credential_id)
            preview_data = current_credential.copy()
            preview_data.update(credential_data)
        except Exception:
            validation_issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    field="credential_id",
                    message=f"Credential not found: {credential_id}",
                    suggestion="Verify the credential ID exists and is accessible",
                    business_impact="Cannot update non-existent credential",
                )
            )
            preview_data = credential_data.copy()

        # Validate field constraints
        validation_issues.extend(await self._validate_field_constraints(credential_data))

        # Check for immutable field changes
        validation_issues.extend(
            await self._check_immutable_fields(current_credential, credential_data)
        )

        # Check for conflicts
        validation_issues.extend(await self._check_update_conflicts(credential_id, credential_data))

        # Analyze billing impact
        billing_impact = await self._analyze_billing_impact(
            "update", credential_data, current_credential
        )

        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(validation_issues)

        # Generate next steps
        next_steps = self._generate_next_steps("update", validation_issues, billing_impact)

        return DryRunResult(
            operation="update",
            valid=not any(
                issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
                for issue in validation_issues
            ),
            validation_issues=validation_issues,
            billing_impact=billing_impact,
            preview_data=preview_data,
            confidence_score=confidence_score,
            next_steps=next_steps,
        )

    async def _validate_required_fields(
        self, operation: str, credential_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate required fields for the operation."""
        issues = []
        required_fields = self.validation_rules["required_fields"].get(operation, [])

        for field in required_fields:
            if field not in credential_data or not credential_data[field]:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        field=field,
                        message=f"Required field '{field}' is missing or empty",
                        suggestion=f"Provide a valid value for '{field}'",
                        business_impact="Cannot proceed without required fields",
                    )
                )

        return issues

    async def _validate_field_constraints(
        self, credential_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate field constraints and formats."""
        issues = []

        for field, value in credential_data.items():
            if field in self.validation_rules["field_constraints"]:
                constraints = self.validation_rules["field_constraints"][field]

                # Length constraints
                if isinstance(value, str):
                    if "min_length" in constraints and len(value) < constraints["min_length"]:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                field=field,
                                message=f"Field '{field}' is too short (minimum {constraints['min_length']} characters)",
                                suggestion=f"Provide a longer value for '{field}'",
                                business_impact="Short values may cause authentication or identification issues",
                            )
                        )

                    if "max_length" in constraints and len(value) > constraints["max_length"]:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                field=field,
                                message=f"Field '{field}' is too long (maximum {constraints['max_length']} characters)",
                                suggestion=f"Shorten the value for '{field}'",
                                business_impact="Long values may be truncated or cause system errors",
                            )
                        )

                # Array constraints
                elif isinstance(value, list) and field == "tags":
                    if len(value) > constraints.get("max_count", 10):
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.WARNING,
                                field=field,
                                message=f"Too many tags (maximum {constraints['max_count']})",
                                suggestion="Reduce the number of tags or combine similar ones",
                                business_impact="Excessive tags may impact performance and usability",
                            )
                        )

        return issues

    async def _check_create_conflicts(
        self, credential_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Check for conflicts during credential creation."""
        issues = []

        # Check for duplicate external IDs
        if "externalId" in credential_data:
            try:
                # Search for existing credentials with the same external ID
                existing_credentials = await self.client.get_credentials(page=0, size=100)
                credentials = self.client._extract_embedded_data(existing_credentials)

                for cred in credentials:
                    if cred.get("externalId") == credential_data["externalId"]:
                        # SECURITY: Obfuscate sensitive data in error messages
                        obfuscated_id = obfuscate_sensitive_string(credential_data["externalId"])
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                field="externalId",
                                message=f"External ID '{obfuscated_id}' already exists",
                                suggestion="Use a unique external ID or update the existing credential",
                                business_impact="Duplicate external IDs can cause authentication conflicts",
                            )
                        )
                        break
            except Exception as e:
                logger.warning(f"Could not check for duplicate external IDs: {e}")

        return issues

    async def _check_update_conflicts(
        self, credential_id: str, credential_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Check for conflicts during credential updates."""
        issues = []

        # Similar to create conflicts but exclude the current credential
        if "externalId" in credential_data:
            try:
                existing_credentials = await self.client.get_credentials(page=0, size=100)
                credentials = self.client._extract_embedded_data(existing_credentials)

                for cred in credentials:
                    is_different_credential = cred.get("id") != credential_id
                    has_same_external_id = cred.get("externalId") == credential_data["externalId"]
                    if is_different_credential and has_same_external_id:
                        # SECURITY: Obfuscate sensitive data in error messages
                        obfuscated_id = obfuscate_sensitive_string(credential_data["externalId"])
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                field="externalId",
                                message=f"External ID '{obfuscated_id}' already exists on another credential",
                                suggestion="Use a unique external ID",
                                business_impact="Duplicate external IDs can cause authentication conflicts",
                            )
                        )
                        break
            except Exception as e:
                logger.warning(f"Could not check for duplicate external IDs: {e}")

        return issues

    async def _check_immutable_fields(
        self, current_credential: Dict[str, Any], update_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Check for changes to immutable fields."""
        issues = []
        immutable_fields = self.validation_rules["business_rules"]["immutable_fields"]

        for field in immutable_fields:
            if field in update_data and field in current_credential:
                if update_data[field] != current_credential[field]:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            field=field,
                            message=f"Field '{field}' cannot be changed after creation",
                            suggestion=f"Remove '{field}' from update data or create a new credential",
                            business_impact="Changing immutable fields can break billing and organizational relationships",
                        )
                    )

        return issues

    async def _validate_business_relationships(
        self, credential_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate business relationships and dependencies."""
        issues = []

        # Validate subscriber exists
        if "subscriberId" in credential_data:
            try:
                # This would check if subscriber exists - simplified for now
                pass
            except Exception:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        field="subscriberId",
                        message="Could not verify subscriber existence",
                        suggestion="Verify the subscriber ID is valid",
                        business_impact="Invalid subscriber may cause billing issues",
                    )
                )

        return issues

    async def _analyze_billing_impact(
        self,
        operation: str,
        credential_data: Dict[str, Any],
        current_credential: Optional[Dict[str, Any]] = None,
    ) -> BillingImpact:
        """Analyze billing implications of the credential operation."""
        affected_subscriptions = []

        # Check for subscription associations
        if "subscriptionIds" in credential_data:
            affected_subscriptions = credential_data["subscriptionIds"]
        elif current_credential and "subscriptionIds" in current_credential:
            affected_subscriptions = current_credential["subscriptionIds"]

        # Determine metering impact
        metering_impact = "No direct impact on metering"
        if operation == "create":
            metering_impact = "New credential will enable metering for associated subscriptions"
        elif operation == "update" and "externalSecret" in credential_data:
            metering_impact = (
                "Secret changes may temporarily disrupt metering until systems are updated"
            )

        # Cost implications
        cost_implications = "No direct cost impact"
        if affected_subscriptions:
            cost_implications = (
                f"May affect billing for {len(affected_subscriptions)} subscription(s)"
            )

        # Automation risk
        automation_risk = "Low risk"
        if operation == "delete" or ("externalSecret" in credential_data and current_credential):
            automation_risk = "Medium to high risk - may disrupt automated billing processes"

        # Recommendations
        recommendations = []
        if affected_subscriptions:
            recommendations.append("Verify all affected subscriptions are properly configured")
            recommendations.append("Consider testing with a single subscription first")

        if operation == "update" and "externalSecret" in credential_data:
            recommendations.append("Update all systems using this credential after the change")
            recommendations.append("Monitor billing automation for 24-48 hours after the change")

        return BillingImpact(
            affected_subscriptions=affected_subscriptions,
            metering_impact=metering_impact,
            cost_implications=cost_implications,
            automation_risk=automation_risk,
            recommendations=recommendations,
        )

    def _calculate_confidence_score(self, validation_issues: List[ValidationIssue]) -> float:
        """Calculate confidence score based on validation issues."""
        if not validation_issues:
            return 1.0

        # Deduct points based on severity
        score = 1.0
        for issue in validation_issues:
            if issue.severity == ValidationSeverity.CRITICAL:
                score -= 0.4
            elif issue.severity == ValidationSeverity.ERROR:
                score -= 0.2
            elif issue.severity == ValidationSeverity.WARNING:
                score -= 0.1
            elif issue.severity == ValidationSeverity.INFO:
                score -= 0.05

        return max(0.0, score)

    def _generate_next_steps(
        self,
        operation: str,
        validation_issues: List[ValidationIssue],
        billing_impact: BillingImpact,
    ) -> List[str]:
        """Generate actionable next steps based on validation results."""
        next_steps = []

        # Address critical and error issues first
        critical_issues = [
            issue
            for issue in validation_issues
            if issue.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.ERROR]
        ]
        if critical_issues:
            next_steps.append("🔴 Address critical validation errors before proceeding")
            for issue in critical_issues[:3]:  # Show top 3
                next_steps.append(f"   • {issue.suggestion}")

        # Address warnings
        warning_issues = [
            issue for issue in validation_issues if issue.severity == ValidationSeverity.WARNING
        ]
        if warning_issues:
            next_steps.append("🟡 Consider addressing validation warnings")

        # Billing recommendations
        if billing_impact.recommendations:
            next_steps.append("💰 Billing recommendations:")
            next_steps.extend([f"   • {rec}" for rec in billing_impact.recommendations[:2]])

        # Operation-specific steps
        if not critical_issues:
            if operation == "create":
                next_steps.append(
                    "✅ Ready to create credential - use create() without dry_run parameter"
                )
            elif operation == "update":
                next_steps.append(
                    "✅ Ready to update credential - use update() without dry_run parameter"
                )

        return next_steps
