"""Cross-Tier Validator for Revenium MCP Server.

This service provides validation capabilities across the three-tier hierarchy
to ensure referential integrity, prevent orphaned entities, and validate
business rules for operations affecting multiple tiers.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from ..client import ReveniumClient
from .entity_lookup_service import EntityLookupService
from .navigation_service import HierarchyNavigationService


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class OperationType(Enum):
    """Types of operations that can be validated."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LINK = "link"
    UNLINK = "unlink"


@dataclass
class ValidationIssue:
    """Represents a validation issue found during cross-tier validation."""

    severity: ValidationSeverity
    code: str
    message: str
    entity_type: str
    entity_id: Optional[str]
    field: Optional[str]
    suggested_action: Optional[str]
    metadata: Dict[str, Any]


@dataclass
class ValidationResult:
    """Result of a cross-tier validation operation."""

    valid: bool
    operation_type: OperationType
    entity_type: str
    entity_id: Optional[str]
    issues: List[ValidationIssue]
    warnings: List[ValidationIssue]
    metadata: Dict[str, Any]

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(
            issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            for issue in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return any(issue.severity == ValidationSeverity.WARNING for issue in self.issues)


@dataclass
class ImpactAnalysis:
    """Analysis of the impact of an operation on related entities."""

    operation_type: OperationType
    target_entity_type: str
    target_entity_id: str
    affected_entities: Dict[str, List[Dict[str, Any]]]
    impact_severity: ValidationSeverity
    recommendations: List[str]
    safe_to_proceed: bool
    metadata: Dict[str, Any]


class CrossTierValidator:
    """Service for validating operations across the three-tier hierarchy."""

    def __init__(
        self,
        client: Optional[ReveniumClient] = None,
        navigation_service: Optional[HierarchyNavigationService] = None,
        lookup_service: Optional[EntityLookupService] = None,
    ):
        """Initialize the cross-tier validator.

        Args:
            client: ReveniumClient instance for API calls
            navigation_service: HierarchyNavigationService for relationship traversal
            lookup_service: EntityLookupService for entity resolution
        """
        self.client = client or ReveniumClient()
        self.navigation_service = navigation_service or HierarchyNavigationService(self.client)
        self.lookup_service = lookup_service or EntityLookupService(self.client)

        # Business rules configuration
        self.business_rules = {
            "products": {
                "required_fields": ["name", "description"],
                "deletion_checks": ["subscriptions"],
                "orphan_prevention": True,
            },
            "subscriptions": {
                "required_fields": ["name", "product_id"],
                "deletion_checks": ["credentials"],
                "parent_validation": "products",
                "orphan_prevention": True,
            },
            "credentials": {
                "required_fields": [
                    "label",
                    "subscriberId",
                    "organizationId",
                    "externalId",
                    "externalSecret",
                ],
                "parent_validation": "subscriptions",
                "orphan_prevention": False,  # Credentials can exist without subscriptions
            },
        }

    async def initialize(self) -> None:
        """Initialize the validator and its dependencies."""
        logger.info("Initializing CrossTierValidator")
        await self.navigation_service.initialize()
        await self.lookup_service.initialize()
        logger.info("CrossTierValidator initialized successfully")

    # Main Validation Methods

    async def validate_hierarchy_operation(self, operation: Dict[str, Any]) -> ValidationResult:
        """Validate an operation that affects the hierarchy.

        Args:
            operation: Operation details with keys:
                - type: OperationType (create, update, delete, etc.)
                - entity_type: Type of entity being operated on
                - entity_id: ID of entity (for update/delete operations)
                - entity_data: Data for the entity (for create/update operations)

        Returns:
            ValidationResult with validation status and issues
        """
        try:
            operation_type = OperationType(operation.get("type", "create"))
            entity_type = operation.get("entity_type")
            entity_id = operation.get("entity_id")
            entity_data = operation.get("entity_data", {})

            if not entity_type:
                return ValidationResult(
                    valid=False,
                    operation_type=operation_type,
                    entity_type="unknown",
                    entity_id=entity_id,
                    issues=[
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="MISSING_ENTITY_TYPE",
                            message="Entity type is required for validation",
                            entity_type="unknown",
                            entity_id=entity_id,
                            field="entity_type",
                            suggested_action="Specify the entity type (products, subscriptions, credentials)",
                            metadata={},
                        )
                    ],
                    warnings=[],
                    metadata={"operation": operation},
                )

            issues = []
            warnings = []

            # Validate based on operation type
            if operation_type == OperationType.CREATE:
                validation_issues = await self._validate_create_operation(entity_type, entity_data)
                issues.extend(validation_issues)

            elif operation_type == OperationType.UPDATE:
                if entity_id:
                    validation_issues = await self._validate_update_operation(
                        entity_type, entity_id, entity_data
                    )
                    issues.extend(validation_issues)
                else:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="MISSING_ENTITY_ID",
                            message="Entity ID is required for update operations",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field="entity_id",
                            suggested_action="Provide the entity ID for the update operation",
                            metadata={},
                        )
                    )

            elif operation_type == OperationType.DELETE:
                if entity_id:
                    validation_issues = await self._validate_delete_operation(
                        entity_type, entity_id
                    )
                    issues.extend(validation_issues)
                else:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="MISSING_ENTITY_ID",
                            message="Entity ID is required for delete operations",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field="entity_id",
                            suggested_action="Provide the entity ID for the delete operation",
                            metadata={},
                        )
                    )

            elif operation_type in [OperationType.LINK, OperationType.UNLINK]:
                if entity_id:
                    validation_issues = await self._validate_link_operation(
                        operation_type, entity_type, entity_id, entity_data
                    )
                    issues.extend(validation_issues)
                else:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="MISSING_ENTITY_ID",
                            message="Entity ID is required for link/unlink operations",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field="entity_id",
                            suggested_action="Provide the entity ID for the link/unlink operation",
                            metadata={},
                        )
                    )

            # Separate warnings from errors
            errors = [
                issue
                for issue in issues
                if issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            ]
            warnings = [issue for issue in issues if issue.severity == ValidationSeverity.WARNING]

            return ValidationResult(
                valid=len(errors) == 0,
                operation_type=operation_type,
                entity_type=entity_type,
                entity_id=entity_id,
                issues=errors,
                warnings=warnings,
                metadata={
                    "operation": operation,
                    "total_issues": len(issues),
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                },
            )

        except Exception as e:
            logger.error(f"Error validating hierarchy operation: {e}")
            return ValidationResult(
                valid=False,
                operation_type=OperationType.CREATE,
                entity_type=operation.get("entity_type", "unknown"),
                entity_id=operation.get("entity_id"),
                issues=[
                    ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        code="VALIDATION_ERROR",
                        message=f"Validation system error: {str(e)}",
                        entity_type=operation.get("entity_type", "unknown"),
                        entity_id=operation.get("entity_id"),
                        field=None,
                        suggested_action="Check operation parameters and try again",
                        metadata={"error": str(e)},
                    )
                ],
                warnings=[],
                metadata={"operation": operation, "error": str(e)},
            )

    async def validate_entity_relationships(self, entity_data: Dict[str, Any]) -> ValidationResult:
        """Validate the relationships defined in entity data.

        Args:
            entity_data: Entity data containing relationship fields

        Returns:
            ValidationResult with relationship validation status
        """
        try:
            entity_type = entity_data.get("entity_type", "unknown")
            entity_id = entity_data.get("id")

            issues = []

            # Validate product_id for subscriptions
            if entity_type == "subscriptions" and "product_id" in entity_data:
                product_id = entity_data["product_id"]
                if product_id:
                    product_ref = await self.lookup_service.resolve_product(product_id, "id")
                    if not product_ref:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                code="INVALID_PRODUCT_REFERENCE",
                                message=f"Referenced product {product_id} does not exist",
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field="product_id",
                                suggested_action="Use a valid product ID or create the product first",
                                metadata={"referenced_product_id": product_id},
                            )
                        )

            # Validate subscriptionIds for credentials
            if entity_type == "credentials" and "subscriptionIds" in entity_data:
                subscription_ids = entity_data.get("subscriptionIds", [])
                for sub_id in subscription_ids:
                    if sub_id:
                        sub_ref = await self.lookup_service.resolve_subscription(sub_id, "id")
                        if not sub_ref:
                            issues.append(
                                ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    code="INVALID_SUBSCRIPTION_REFERENCE",
                                    message=f"Referenced subscription {sub_id} does not exist",
                                    entity_type=entity_type,
                                    entity_id=entity_id,
                                    field="subscriptionIds",
                                    suggested_action="Use valid subscription IDs or create the subscriptions first",
                                    metadata={"referenced_subscription_id": sub_id},
                                )
                            )

            # Validate subscriberId for credentials
            if entity_type == "credentials" and "subscriberId" in entity_data:
                subscriber_id = entity_data["subscriberId"]
                if subscriber_id:
                    subscriber_ref = await self.lookup_service.resolve_subscriber(
                        subscriber_id, "id"
                    )
                    if not subscriber_ref:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                code="INVALID_SUBSCRIBER_REFERENCE",
                                message=f"Referenced subscriber {subscriber_id} does not exist",
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field="subscriberId",
                                suggested_action="Use a valid subscriber ID or create the subscriber first",
                                metadata={"referenced_subscriber_id": subscriber_id},
                            )
                        )

            # Validate organizationId for credentials
            if entity_type == "credentials" and "organizationId" in entity_data:
                organization_id = entity_data["organizationId"]
                if organization_id:
                    org_ref = await self.lookup_service.resolve_organization(organization_id, "id")
                    if not org_ref:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                code="INVALID_ORGANIZATION_REFERENCE",
                                message=f"Referenced organization {organization_id} does not exist",
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field="organizationId",
                                suggested_action="Use a valid organization ID or create the organization first",
                                metadata={"referenced_organization_id": organization_id},
                            )
                        )

            errors = [
                issue
                for issue in issues
                if issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            ]
            warnings = [issue for issue in issues if issue.severity == ValidationSeverity.WARNING]

            return ValidationResult(
                valid=len(errors) == 0,
                operation_type=OperationType.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                issues=errors,
                warnings=warnings,
                metadata={
                    "entity_data": entity_data,
                    "relationships_checked": [
                        "product_id",
                        "subscriptionIds",
                        "subscriberId",
                        "organizationId",
                    ],
                },
            )

        except Exception as e:
            logger.error(f"Error validating entity relationships: {e}")
            return ValidationResult(
                valid=False,
                operation_type=OperationType.CREATE,
                entity_type=entity_data.get("entity_type", "unknown"),
                entity_id=entity_data.get("id"),
                issues=[
                    ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        code="RELATIONSHIP_VALIDATION_ERROR",
                        message=f"Relationship validation error: {str(e)}",
                        entity_type=entity_data.get("entity_type", "unknown"),
                        entity_id=entity_data.get("id"),
                        field=None,
                        suggested_action="Check entity data and try again",
                        metadata={"error": str(e)},
                    )
                ],
                warnings=[],
                metadata={"entity_data": entity_data, "error": str(e)},
            )

    async def analyze_deletion_impact(self, entity_type: str, entity_id: str) -> ImpactAnalysis:
        """Analyze the impact of deleting an entity on related entities.

        Args:
            entity_type: Type of entity to delete
            entity_id: ID of entity to delete

        Returns:
            ImpactAnalysis with impact details and recommendations
        """
        try:
            affected_entities = {}
            recommendations = []
            impact_severity = ValidationSeverity.INFO
            safe_to_proceed = True

            if entity_type == "products":
                # Check for dependent subscriptions
                nav_result = await self.navigation_service.get_subscriptions_for_product(entity_id)
                if nav_result.success and nav_result.related_entities:
                    affected_entities["subscriptions"] = nav_result.related_entities
                    impact_severity = ValidationSeverity.ERROR
                    safe_to_proceed = False
                    recommendations.append(
                        "Delete or reassign all subscriptions before deleting the product"
                    )

                    # Check for credentials through subscriptions
                    all_credentials = []
                    for subscription in nav_result.related_entities:
                        sub_id = subscription.get("id")
                        if sub_id:
                            cred_result = (
                                await self.navigation_service.get_credentials_for_subscription(
                                    sub_id
                                )
                            )
                            if cred_result.success and cred_result.related_entities:
                                all_credentials.extend(cred_result.related_entities)

                    if all_credentials:
                        affected_entities["credentials"] = all_credentials
                        recommendations.append(
                            "Delete or reassign all credentials before deleting subscriptions"
                        )

            elif entity_type == "subscriptions":
                # Check for dependent credentials
                nav_result = await self.navigation_service.get_credentials_for_subscription(
                    entity_id
                )
                if nav_result.success and nav_result.related_entities:
                    affected_entities["credentials"] = nav_result.related_entities
                    impact_severity = (
                        ValidationSeverity.WARNING
                    )  # Credentials can exist without subscriptions
                    recommendations.append(
                        "Consider reassigning credentials to other subscriptions"
                    )

            elif entity_type == "credentials":
                # Credentials are leaf nodes, minimal impact
                impact_severity = ValidationSeverity.INFO
                recommendations.append("Credential deletion has minimal impact on other entities")

            return ImpactAnalysis(
                operation_type=OperationType.DELETE,
                target_entity_type=entity_type,
                target_entity_id=entity_id,
                affected_entities=affected_entities,
                impact_severity=impact_severity,
                recommendations=recommendations,
                safe_to_proceed=safe_to_proceed,
                metadata={
                    "total_affected_entities": sum(
                        len(entities) for entities in affected_entities.values()
                    ),
                    "entity_types_affected": list(affected_entities.keys()),
                },
            )

        except Exception as e:
            logger.error(f"Error analyzing deletion impact for {entity_type} {entity_id}: {e}")
            return ImpactAnalysis(
                operation_type=OperationType.DELETE,
                target_entity_type=entity_type,
                target_entity_id=entity_id,
                affected_entities={},
                impact_severity=ValidationSeverity.CRITICAL,
                recommendations=["Unable to analyze impact due to error"],
                safe_to_proceed=False,
                metadata={"error": str(e)},
            )

    # Internal Validation Methods

    async def _validate_create_operation(
        self, entity_type: str, entity_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate a create operation."""
        issues = []

        # Check required fields
        rules = self.business_rules.get(entity_type, {})
        required_fields = rules.get("required_fields", [])

        for field in required_fields:
            if field not in entity_data or not entity_data[field]:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="MISSING_REQUIRED_FIELD",
                        message=f"Required field '{field}' is missing or empty",
                        entity_type=entity_type,
                        entity_id=None,
                        field=field,
                        suggested_action=f"Provide a value for the '{field}' field",
                        metadata={"required_fields": required_fields},
                    )
                )

        # Validate parent relationships
        parent_type = rules.get("parent_validation")
        if parent_type:
            if entity_type == "subscriptions" and "product_id" in entity_data:
                product_id = entity_data["product_id"]
                if product_id:
                    product_ref = await self.lookup_service.resolve_product(product_id, "id")
                    if not product_ref:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                code="INVALID_PARENT_REFERENCE",
                                message=f"Parent product {product_id} does not exist",
                                entity_type=entity_type,
                                entity_id=None,
                                field="product_id",
                                suggested_action="Create the product first or use a valid product ID",
                                metadata={"parent_type": parent_type, "parent_id": product_id},
                            )
                        )

        return issues

    async def _validate_update_operation(
        self, entity_type: str, entity_id: str, entity_data: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """Validate an update operation."""
        issues = []

        # Check if entity exists
        if entity_type == "products":
            entity_ref = await self.lookup_service.resolve_product(entity_id, "id")
        elif entity_type == "subscriptions":
            entity_ref = await self.lookup_service.resolve_subscription(entity_id, "id")
        elif entity_type == "credentials":
            entity_ref = await self.lookup_service.resolve_credential(entity_id, "id")
        else:
            entity_ref = None

        if not entity_ref:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="ENTITY_NOT_FOUND",
                    message=f"{entity_type.title()} {entity_id} does not exist",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field=None,
                    suggested_action="Use a valid entity ID or create the entity first",
                    metadata={},
                )
            )

        # Validate relationship changes
        if "product_id" in entity_data and entity_type == "subscriptions":
            new_product_id = entity_data["product_id"]
            if new_product_id:
                product_ref = await self.lookup_service.resolve_product(new_product_id, "id")
                if not product_ref:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="INVALID_PRODUCT_REFERENCE",
                            message=f"New product reference {new_product_id} does not exist",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field="product_id",
                            suggested_action="Use a valid product ID",
                            metadata={"new_product_id": new_product_id},
                        )
                    )

        return issues

    async def _validate_delete_operation(
        self, entity_type: str, entity_id: str
    ) -> List[ValidationIssue]:
        """Validate a delete operation."""
        issues = []

        # Check if entity exists
        if entity_type == "products":
            entity_ref = await self.lookup_service.resolve_product(entity_id, "id")
        elif entity_type == "subscriptions":
            entity_ref = await self.lookup_service.resolve_subscription(entity_id, "id")
        elif entity_type == "credentials":
            entity_ref = await self.lookup_service.resolve_credential(entity_id, "id")
        else:
            entity_ref = None

        if not entity_ref:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="ENTITY_NOT_FOUND",
                    message=f"{entity_type.title()} {entity_id} does not exist",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    field=None,
                    suggested_action="Use a valid entity ID",
                    metadata={},
                )
            )
            return issues

        # Check for dependent entities
        rules = self.business_rules.get(entity_type, {})
        deletion_checks = rules.get("deletion_checks", [])

        for dependent_type in deletion_checks:
            if entity_type == "products" and dependent_type == "subscriptions":
                nav_result = await self.navigation_service.get_subscriptions_for_product(entity_id)
                if nav_result.success and nav_result.related_entities:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="HAS_DEPENDENT_ENTITIES",
                            message=f"Cannot delete product: {len(nav_result.related_entities)} dependent subscriptions exist",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field=None,
                            suggested_action="Delete or reassign dependent subscriptions first",
                            metadata={
                                "dependent_count": len(nav_result.related_entities),
                                "dependent_type": dependent_type,
                            },
                        )
                    )

            elif entity_type == "subscriptions" and dependent_type == "credentials":
                nav_result = await self.navigation_service.get_credentials_for_subscription(
                    entity_id
                )
                if nav_result.success and nav_result.related_entities:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,  # Warning since credentials can exist without subscriptions
                            code="HAS_DEPENDENT_ENTITIES",
                            message=f"Deleting subscription will affect {len(nav_result.related_entities)} credentials",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field=None,
                            suggested_action="Consider reassigning credentials to other subscriptions",
                            metadata={
                                "dependent_count": len(nav_result.related_entities),
                                "dependent_type": dependent_type,
                            },
                        )
                    )

        return issues

    async def _validate_link_operation(
        self,
        operation_type: OperationType,
        entity_type: str,
        entity_id: str,
        entity_data: Dict[str, Any],
    ) -> List[ValidationIssue]:
        """Validate a link/unlink operation."""
        issues = []

        # Validate that both entities exist
        if entity_type == "credentials" and "subscriptionIds" in entity_data:
            # Validate credential exists
            cred_ref = await self.lookup_service.resolve_credential(entity_id, "id")
            if not cred_ref:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="ENTITY_NOT_FOUND",
                        message=f"Credential {entity_id} does not exist",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        field=None,
                        suggested_action="Use a valid credential ID",
                        metadata={},
                    )
                )

            # Validate subscription IDs
            subscription_ids = entity_data.get("subscriptionIds", [])
            for sub_id in subscription_ids:
                if sub_id:
                    sub_ref = await self.lookup_service.resolve_subscription(sub_id, "id")
                    if not sub_ref:
                        issues.append(
                            ValidationIssue(
                                severity=ValidationSeverity.ERROR,
                                code="INVALID_SUBSCRIPTION_REFERENCE",
                                message=f"Subscription {sub_id} does not exist",
                                entity_type=entity_type,
                                entity_id=entity_id,
                                field="subscriptionIds",
                                suggested_action="Use valid subscription IDs",
                                metadata={"invalid_subscription_id": sub_id},
                            )
                        )

        return issues

    async def check_referential_integrity(
        self, entity_type: str, entity_id: str
    ) -> ValidationResult:
        """Check referential integrity for a specific entity.

        Args:
            entity_type: Type of entity to check
            entity_id: ID of entity to check

        Returns:
            ValidationResult with integrity check results
        """
        try:
            issues = []

            # Get the entity data
            if entity_type == "products":
                entity_ref = await self.lookup_service.resolve_product(entity_id, "id")
            elif entity_type == "subscriptions":
                entity_ref = await self.lookup_service.resolve_subscription(entity_id, "id")
            elif entity_type == "credentials":
                entity_ref = await self.lookup_service.resolve_credential(entity_id, "id")
            else:
                return ValidationResult(
                    valid=False,
                    operation_type=OperationType.CREATE,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    issues=[
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="UNKNOWN_ENTITY_TYPE",
                            message=f"Unknown entity type: {entity_type}",
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field=None,
                            suggested_action="Use a valid entity type (products, subscriptions, credentials)",
                            metadata={},
                        )
                    ],
                    warnings=[],
                    metadata={},
                )

            if not entity_ref:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="ENTITY_NOT_FOUND",
                        message=f"{entity_type.title()} {entity_id} does not exist",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        field=None,
                        suggested_action="Use a valid entity ID",
                        metadata={},
                    )
                )
            else:
                # Check relationships based on entity type
                entity_data = entity_ref.entity_data

                if entity_type == "subscriptions":
                    # Check product reference
                    product_id = entity_data.get("product_id") or entity_data.get("productId")
                    if product_id:
                        product_ref = await self.lookup_service.resolve_product(product_id, "id")
                        if not product_ref:
                            issues.append(
                                ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    code="BROKEN_PRODUCT_REFERENCE",
                                    message=f"Subscription references non-existent product {product_id}",
                                    entity_type=entity_type,
                                    entity_id=entity_id,
                                    field="product_id",
                                    suggested_action="Update product reference or create the missing product",
                                    metadata={"broken_product_id": product_id},
                                )
                            )

                elif entity_type == "credentials":
                    # Check subscription references
                    subscription_ids = entity_data.get("subscriptionIds", [])
                    for sub_id in subscription_ids:
                        if sub_id:
                            sub_ref = await self.lookup_service.resolve_subscription(sub_id, "id")
                            if not sub_ref:
                                issues.append(
                                    ValidationIssue(
                                        severity=ValidationSeverity.ERROR,
                                        code="BROKEN_SUBSCRIPTION_REFERENCE",
                                        message=f"Credential references non-existent subscription {sub_id}",
                                        entity_type=entity_type,
                                        entity_id=entity_id,
                                        field="subscriptionIds",
                                        suggested_action="Update subscription reference or create the missing subscription",
                                        metadata={"broken_subscription_id": sub_id},
                                    )
                                )

                    # Check subscriber reference
                    subscriber_id = entity_data.get("subscriberId")
                    if subscriber_id:
                        subscriber_ref = await self.lookup_service.resolve_subscriber(
                            subscriber_id, "id"
                        )
                        if not subscriber_ref:
                            issues.append(
                                ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    code="BROKEN_SUBSCRIBER_REFERENCE",
                                    message=f"Credential references non-existent subscriber {subscriber_id}",
                                    entity_type=entity_type,
                                    entity_id=entity_id,
                                    field="subscriberId",
                                    suggested_action="Update subscriber reference or create the missing subscriber",
                                    metadata={"broken_subscriber_id": subscriber_id},
                                )
                            )

                    # Check organization reference
                    organization_id = entity_data.get("organizationId")
                    if organization_id:
                        org_ref = await self.lookup_service.resolve_organization(
                            organization_id, "id"
                        )
                        if not org_ref:
                            issues.append(
                                ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    code="BROKEN_ORGANIZATION_REFERENCE",
                                    message=f"Credential references non-existent organization {organization_id}",
                                    entity_type=entity_type,
                                    entity_id=entity_id,
                                    field="organizationId",
                                    suggested_action="Update organization reference or create the missing organization",
                                    metadata={"broken_organization_id": organization_id},
                                )
                            )

            errors = [
                issue
                for issue in issues
                if issue.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            ]
            warnings = [issue for issue in issues if issue.severity == ValidationSeverity.WARNING]

            return ValidationResult(
                valid=len(errors) == 0,
                operation_type=OperationType.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                issues=errors,
                warnings=warnings,
                metadata={"integrity_check": True, "entity_exists": entity_ref is not None},
            )

        except Exception as e:
            logger.error(f"Error checking referential integrity for {entity_type} {entity_id}: {e}")
            return ValidationResult(
                valid=False,
                operation_type=OperationType.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                issues=[
                    ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        code="INTEGRITY_CHECK_ERROR",
                        message=f"Integrity check error: {str(e)}",
                        entity_type=entity_type,
                        entity_id=entity_id,
                        field=None,
                        suggested_action="Check entity data and try again",
                        metadata={"error": str(e)},
                    )
                ],
                warnings=[],
                metadata={"error": str(e)},
            )


# Global service instance (lazy initialization)
_cross_tier_validator = None


def get_cross_tier_validator() -> CrossTierValidator:
    """Get the global cross tier validator instance (lazy initialization)."""
    global _cross_tier_validator
    if _cross_tier_validator is None:
        _cross_tier_validator = CrossTierValidator()
    return _cross_tier_validator


# For backward compatibility
def cross_tier_validator() -> CrossTierValidator:
    """Backward compatibility function."""
    return get_cross_tier_validator()
