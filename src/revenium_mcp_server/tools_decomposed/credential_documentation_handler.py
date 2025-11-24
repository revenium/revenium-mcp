"""Documentation and examples handler for subscriber credentials management.

This module handles capabilities, examples, validation, agent summaries,
and natural language processing for credential operations.
"""

from typing import Any, Dict

from ..common.error_handling import create_structured_missing_parameter_error
from ..nlp.credential_nlp_processor import CredentialNLPProcessor


class CredentialDocumentationHandler:
    """Handler for documentation and examples in credential management."""

    def __init__(self):
        """Initialize documentation handler."""
        self.nlp_processor = CredentialNLPProcessor()

    async def get_capabilities(self, arguments: Dict[str, Any]) -> str:
        """Get tool capabilities and supported operations formatted as markdown."""
        result_text = "# **Subscriber Credentials Management Capabilities**\n\n"

        # Parameter Organization section (critical for agent understanding)
        result_text += "## **Parameter Organization**\n\n"
        result_text += "**Creation fields** must be nested in `credential_data` container:\n"
        result_text += "```json\n"
        result_text += ('{"action": "create", "credential_data": {"label": "API Key", '
                        '"subscriberId": "sub_123", "organizationId": "org_456", '
                        '"externalId": "***EXAMPLE_KEY***", "externalSecret": "***EXAMPLE_SECRET***"}}\n')
        result_text += "```\n\n"
        result_text += "**Top-level parameters** for tool behavior:\n"
        result_text += "- `action` - What operation to perform (default: get_capabilities)\n"
        result_text += "- `credential_id` - For get/update/delete operations\n"
        result_text += "- `dry_run` - Preview without creating (optional)\n"
        result_text += "- `page`, `size` - For list operations\n\n"

        # CRUD Operations
        result_text += "## **CRUD Operations**\n\n"
        result_text += "### **Create**\n"
        result_text += "- Create new subscriber credentials\n"
        result_text += "- Establishes authentication for billing and usage tracking\n"
        result_text += "- Supports dry-run validation\n\n"

        result_text += "### **Read**\n"
        result_text += "- `list` - Get paginated list of credentials\n"
        result_text += "- `get` - Get specific credential by ID\n\n"

        result_text += "### **Update**\n"
        result_text += "- Update existing credential properties\n"
        result_text += "- Supports partial updates\n"
        result_text += "- All fields except system fields are updatable\n\n"

        result_text += "### **Delete**\n"
        result_text += "- Delete credential permanently\n"
        result_text += "- **Warning**: This action cannot be undone\n\n"

        # Field Requirements
        result_text += "## **Field Requirements**\n\n"
        result_text += "### **Required Fields** (for creation)\n"
        result_text += "- `label` - Display name for the credential\n"
        result_text += ("- `subscriberId` - ID of the subscriber "
                        "(use resolve_subscriber_email_to_id if needed)\n")
        result_text += ("- `organizationId` - ID of the organization "
                        "(use resolve_organization_name_to_id if needed)\n")
        result_text += "- `externalId` - External credential identifier\n"
        result_text += "- `externalSecret` - Secret/password for the credential\n\n"

        result_text += "### **Optional Fields**\n"
        result_text += "- `name` - Internal name (typically same as label)\n"
        result_text += "- `tags` - Array of tags for categorization\n"
        result_text += "- `subscriptionIds` - Array of subscription IDs to associate\n\n"

        # Helper Operations
        result_text += "## **Helper Operations**\n"
        result_text += "- `resolve_subscriber_email_to_id` - Convert subscriber email to ID\n"
        result_text += ("- `resolve_organization_name_to_id` - Convert organization name to ID\n\n")

        # Validation and Testing
        result_text += "## **Validation and Testing**\n"
        result_text += "- `validate` - Validate credential data structure\n"
        result_text += "- `get_examples` - Get comprehensive usage examples\n"
        result_text += "- Dry-run support for all operations\n\n"

        # Business Rules
        result_text += "## **Business Rules**\n"
        result_text += ("- Credential operations affect authentication for billing and "
                        "usage tracking\n")
        result_text += ("- External secrets should be strong and secure "
                        "(minimum 8 characters recommended)\n")
        result_text += "- Labels should be descriptive (minimum 3 characters)\n"
        result_text += "- Subscriber and organization IDs must reference existing entities\n"
        result_text += "- Deletion is permanent and cannot be undone\n\n"

        # Authentication Requirements
        result_text += "## **Authentication Requirements**\n"
        result_text += "- API key authentication required\n"
        result_text += ("- Environment variables: `REVENIUM_API_KEY`, `REVENIUM_TEAM_ID`\n\n")

        # Dependencies
        result_text += "## **Dependencies**\n"
        result_text += ("- `manage_customers` - Required for subscriber and organization "
                        "lookups\n\n")

        # Next Steps
        result_text += "## **Next Steps**\n"
        result_text += "1. Use `get_examples()` to see working credential templates\n"
        result_text += "2. Use `validate(credential_data={...})` to test configurations\n"
        result_text += "3. Use `create(credential_data={...})` to create credentials\n"
        result_text += ("4. Use helper methods to resolve email/organization names to IDs\n")

        return result_text

    async def get_examples(self, arguments: Dict[str, Any]) -> str:
        """Get comprehensive usage examples formatted as markdown."""
        example_type = arguments.get("example_type", "basic")

        # Return formatted markdown based on example type
        if example_type == "basic" or example_type not in ["field_mapping", "validation", "nlp"]:
            return self._format_basic_examples()
        elif example_type == "field_mapping":
            return self._format_field_mapping_examples()
        elif example_type == "validation":
            return self._format_validation_examples()
        elif example_type == "nlp":
            return self._format_nlp_examples()
        else:
            return self._format_all_examples()

    def _format_basic_examples(self) -> str:
        """Format basic credential management examples."""
        result_text = "**Subscriber Credentials Management Examples**\n\n"

        result_text += "## **Recommended Example**\n\n"
        result_text += "**Type**: `basic_credential`\n"
        result_text += "**Description**: Create subscriber credential for API authentication\n"
        result_text += "**Use Case**: Most common pattern - establish billing identity for usage tracking\n\n"

        result_text += "**Template**:\n"
        result_text += "```json\n"
        result_text += "{\n"
        result_text += '  "action": "create",\n'
        result_text += '  "credential_data": {\n'
        result_text += '    "label": "Production API Key",\n'
        result_text += '    "subscriberId": "SUBSCRIBER_ID_FROM_LIST",\n'
        result_text += '    "organizationId": "ORGANIZATION_ID_FROM_LIST",\n'
        result_text += '    "externalId": "***YOUR_API_KEY***",\n'
        result_text += '    "externalSecret": "***YOUR_SECRET***",\n'
        result_text += '    "tags": ["production", "api"]\n'
        result_text += "  }\n"
        result_text += "}\n"
        result_text += "```\n\n"

        result_text += "## **Prerequisites**\n"
        result_text += "**REQUIRED**: Get valid IDs first to avoid 404 errors:\n"
        result_text += "1. List subscribers: `manage_customers(action='list', resource_type='subscribers')`\n"
        result_text += "2. List organizations: `manage_customers(action='list', resource_type='organizations')`\n"
        result_text += "3. Copy valid subscriberId and organizationId from the results\n\n"

        result_text += "## **Basic Operations**\n\n"
        result_text += "### **List Credentials**\n"
        result_text += "```bash\n"
        result_text += "list(page=0, size=20)\n"
        result_text += "```\n"
        result_text += "Returns paginated list of credentials with metadata\n\n"

        result_text += "### **Get Specific Credential**\n"
        result_text += "```bash\n"
        result_text += "get(credential_id='jM7Xg7j')\n"
        result_text += "```\n"
        result_text += "Returns detailed credential information\n\n"

        result_text += "### **Update Credential**\n"
        result_text += "```bash\n"
        result_text += "update(credential_id='jM7Xg7j', credential_data={'label': 'Updated API Key', 'externalSecret': '***NEW_SECRET***'})\n"
        result_text += "```\n"
        result_text += "Supports partial updates of any field\n\n"

        result_text += "### **Delete Credential**\n"
        result_text += "```bash\n"
        result_text += "delete(credential_id='jM7Xg7j')\n"
        result_text += "```\n"
        result_text += "**Warning**: This action cannot be undone\n\n"

        result_text += "## **Usage**\n"
        result_text += "1. Get valid subscriber and organization IDs first\n"
        result_text += "2. Copy the recommended template above\n"
        result_text += "3. Replace placeholder IDs with real values\n"
        result_text += "4. Use `validate` to test your configuration\n"
        result_text += "5. Use `create` action to create the credential\n\n"

        result_text += "**Pro Tip**: Always use `validate` before `create` to catch errors early!\n"

        return result_text

    def _format_field_mapping_examples(self) -> str:
        """Format field mapping examples."""
        result_text = "**Field Mapping Examples**\n\n"
        result_text += "## **Browser Form to API Mapping**\n"
        result_text += "- Subscriber Credential Name → `label` and `name`\n"
        result_text += "- Subscriber E-Mail → `subscriberId` (resolve email to ID)\n"
        result_text += "- Organization → `organizationId` (resolve name to ID)\n"
        result_text += "- Credential ID → `externalId`\n"
        result_text += "- External Secret → `externalSecret`\n"
        result_text += "- Subscription → `subscriptionIds` (array)\n"
        result_text += "- Tags → `tags` (array)\n\n"

        result_text += "## **Helper Methods**\n"
        result_text += "```python\n"
        result_text += "# Resolve subscriber email to ID\n"
        result_text += "await client.resolve_subscriber_email_to_id('user@company.com')\n\n"
        result_text += "# Resolve organization name to ID\n"
        result_text += "await client.resolve_organization_name_to_id('Company Name')\n"
        result_text += "```\n"

        return result_text

    def _format_validation_examples(self) -> str:
        """Format validation examples."""
        result_text = "**Validation Examples**\n\n"
        result_text += "## **Validate Credential Data**\n"
        result_text += "```bash\n"
        result_text += "validate(credential_data={...})\n"
        result_text += "```\n\n"
        result_text += "**Validation Checks**:\n"
        result_text += "- Required fields presence\n"
        result_text += "- Field data types\n"
        result_text += "- Data format validation\n"

        return result_text

    def _format_nlp_examples(self) -> str:
        """Format NLP examples."""
        result_text = "**Natural Language Processing Examples**\n\n"
        result_text += "## **Parse Natural Language**\n"
        result_text += "```bash\n"
        result_text += "parse_natural_language(text='Create API key for john@company.com at Acme Corp with secret abc123')\n"
        result_text += "```\n\n"
        result_text += "**Supported Patterns**:\n"
        result_text += "- Create [credential type] for [email] at [organization] with secret [value]\n"
        result_text += "- Add new credential for [subscriber] in [organization]\n"
        result_text += "- Set up authentication for [email] with key [value]\n"

        return result_text

    def _format_all_examples(self) -> str:
        """Format all available examples."""
        result_text = "**All Available Examples**\n\n"
        result_text += "## **Available Example Types**\n"
        result_text += "- `basic` - Basic CRUD operations (default)\n"
        result_text += "- `field_mapping` - Browser form to API field mapping\n"
        result_text += "- `validation` - Data validation examples\n"
        result_text += "- `nlp` - Natural language processing examples\n\n"
        result_text += "Use `get_examples(example_type='...')` to see specific examples.\n"

        return result_text

    async def validate_credential_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate credential data structure and fields."""
        credential_data = arguments.get("credential_data")
        operation_type = arguments.get(
            "operation_type", "create"
        )  # Default to create for backward compatibility

        if not credential_data:
            raise create_structured_missing_parameter_error(
                parameter_name="credential_data",
                action="validate credential data",
                examples={
                    "usage": "validate(credential_data={...})",
                    "usage_update": "validate(credential_data={...}, operation_type='update')",
                    "example_data": {
                        "label": "API Key",
                        "subscriberId": "sub_123",
                        "organizationId": "org_456",
                        "externalId": "***YOUR_KEY***",
                        "externalSecret": "***YOUR_SECRET***",
                    },
                },
            )

        validation_results = {
            "action": "validate",
            "operation_type": operation_type,
            "valid": True,
            "errors": [],
            "warnings": [],
            "field_checks": {},
        }

        # Check required fields based on operation type
        if operation_type == "create":
            # For CREATE operations, all fields are required
            required_fields = [
                "label",
                "subscriberId",
                "organizationId",
                "externalId",
                "externalSecret",
            ]
            for field in required_fields:
                if field not in credential_data or not credential_data[field]:
                    validation_results["errors"].append(f"Missing required field: {field}")
                    validation_results["valid"] = False
                    validation_results["field_checks"][field] = "missing"
                else:
                    validation_results["field_checks"][field] = "valid"
        else:
            # For UPDATE operations, only validate provided fields
            # No fields are strictly required since it's a partial update
            for field in credential_data.keys():
                if credential_data[field] is not None and credential_data[field] != "":
                    validation_results["field_checks"][field] = "valid"
                else:
                    validation_results["warnings"].append(f"Field '{field}' is empty or null")
                    validation_results["field_checks"][field] = "empty"

        # Check field types
        field_types = {
            "label": str,
            "name": str,
            "subscriberId": str,
            "organizationId": str,
            "externalId": str,
            "externalSecret": str,
            "tags": list,
            "subscriptionIds": list,
        }

        for field, expected_type in field_types.items():
            if field in credential_data:
                if not isinstance(credential_data[field], expected_type):
                    validation_results["errors"].append(
                        f"Field '{field}' should be of type {expected_type.__name__}"
                    )
                    validation_results["valid"] = False
                    validation_results["field_checks"][
                        field
                    ] = f"invalid_type (expected {expected_type.__name__})"

        # Check for common issues
        if "label" in credential_data and len(credential_data["label"]) < 3:
            validation_results["warnings"].append("Label should be at least 3 characters long")

        if "externalSecret" in credential_data and len(credential_data["externalSecret"]) < 8:
            validation_results["warnings"].append(
                "External secret should be at least 8 characters long for security"
            )

        return validation_results

    async def get_agent_summary(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get agent-friendly summary of subscriber credentials management capabilities."""
        return {
            "action": "get_agent_summary",
            "tool_name": "manage_subscriber_credentials",
            "description": "Comprehensive subscriber credentials management with CRUD operations and enhanced capabilities",
            "quick_start": {
                "1_list_credentials": "list() - Get all subscriber credentials",
                "2_get_credential": "get(credential_id='cred_123') - Get specific credential",
                "3_create_credential": "create(credential_data={...}) - Create new credential",
                "4_update_credential": "update(credential_id='cred_123', credential_data={...}) - Update credential",
                "5_delete_credential": "delete(credential_id='cred_123') - Delete credential",
            },
            "key_features": [
                "🔐 Full CRUD operations for subscriber credentials",
                "📧 Email-to-ID resolution for subscribers",
                "🏢 Organization name-to-ID resolution",
                "✅ Comprehensive field validation",
                "🤖 Natural language processing support",
                "📚 Rich examples and documentation",
                "🔒 Billing safety warnings and guidance",
            ],
            "common_workflows": {
                "create_new_credential": [
                    "1. Resolve subscriber email to ID if needed",
                    "2. Resolve organization name to ID if needed",
                    "3. Prepare credential data with required fields",
                    "4. Call create() with credential_data",
                    "5. Verify creation with get() using returned ID",
                ],
                "update_existing_credential": [
                    "1. Get current credential with get(credential_id)",
                    "2. Modify desired fields in credential data",
                    "3. Call update() with credential_id and updated data",
                    "4. Verify update with get() to confirm changes",
                ],
            },
            "required_fields_for_create": [
                "label",
                "subscriberId",
                "organizationId",
                "externalId",
                "externalSecret",
            ],
            "helper_methods": {
                "resolve_subscriber_email_to_id": "Convert subscriber email to ID for subscriberId field",
                "resolve_organization_name_to_id": "Convert organization name to ID for organizationId field",
            },
            "safety_notes": [
                "🔒 Credential operations affect authentication for billing and usage tracking",
                "⚠️ Deletion is permanent and cannot be undone",
                "🔐 External secrets should be strong and secure",
                "📋 Always validate data before submission",
            ],
        }

    async def parse_natural_language(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Parse natural language descriptions into credential data."""
        text = arguments.get("text") or arguments.get("description")
        if not text:
            raise create_structured_missing_parameter_error(
                parameter_name="text",
                action="parse natural language",
                examples={
                    "usage": "parse_natural_language(text='Create API key for john@company.com at Acme Corp with secret abc123')",
                    "supported_patterns": [
                        "Create [credential type] for [email] at [organization] with secret [value]",
                        "Add new credential for [subscriber] in [organization]",
                        "Set up authentication for [email] with key [value]",
                    ],
                },
            )

        # Use the NLP processor
        nlp_result = await self.nlp_processor.process_natural_language(text)

        # Convert to dictionary format
        return {
            "action": "parse_natural_language",
            "input_text": text,
            "intent": nlp_result.intent.value,
            "confidence": nlp_result.confidence,
            "extracted_entities": {
                entity_type: {
                    "value": entity.value,
                    "confidence": entity.confidence,
                    "context": entity.context,
                }
                for entity_type, entity in nlp_result.entities.items()
            },
            "extracted_data": self.nlp_processor.extract_credential_data(nlp_result),
            "suggestions": nlp_result.suggestions,
            "warnings": nlp_result.warnings,
            "business_context": nlp_result.business_context,
        }
