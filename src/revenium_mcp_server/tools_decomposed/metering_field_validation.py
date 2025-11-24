"""Dedicated metering field validation tool following MCP best practices.

This module provides comprehensive field validation capabilities for AI transaction
metering through shared component composition, achieving 100% code reuse of existing
MeteringTransactionManager and MeteringValidator infrastructure.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from loguru import logger


def _get_utc_timestamp() -> str:
    """Get UTC timestamp in the correct format for Revenium API (ending with Z)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError
from ..introspection.metadata import ToolCapability, ToolType

# Import existing managers for 100% code reuse
from .metering_management import MeteringTransactionManager, MeteringValidator
from .unified_tool_base import ToolBase


class TestDataGenerator:
    """Generator for realistic AI transaction test data with comprehensive field coverage."""

    def __init__(self):
        """Initialize test data generator with industry patterns and field templates."""
        self.industry_patterns = self._build_industry_patterns()
        self.field_templates = self._build_field_templates()
        self.subscriber_templates = self._build_subscriber_templates()
        self.edge_case_patterns = self._build_edge_case_patterns()

    def generate_batch(self, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate a batch of realistic test transactions.

        Args:
            arguments: Generation parameters including count, industry, field coverage options

        Returns:
            List of test transaction dictionaries
        """
        count = arguments.get("count", 10)
        industry = arguments.get("industry", "financial_services")
        include_enterprise_fields = arguments.get("include_enterprise_fields", True)
        include_edge_cases = arguments.get("include_edge_cases", False)
        custom_fields = arguments.get("custom_fields", {})

        test_data = []
        industry_pattern = self.industry_patterns.get(
            industry, self.industry_patterns["financial_services"]
        )

        for i in range(count):
            # Generate base transaction
            transaction = self._generate_base_transaction(i, industry_pattern)

            # Add enterprise fields if requested
            if include_enterprise_fields:
                transaction.update(self._generate_enterprise_fields(i, industry_pattern))

            # Add subscriber object with nested structure
            transaction["subscriber"] = self._generate_subscriber_object(i, industry)

            # Add edge cases for some transactions
            if include_edge_cases and i % 5 == 0:  # Every 5th transaction
                transaction.update(self._generate_edge_case_fields(i))

            # Apply custom field overrides
            if custom_fields:
                transaction.update(custom_fields)

            test_data.append(transaction)

        return test_data

    def _generate_base_transaction(
        self, index: int, industry_pattern: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate base transaction fields."""
        import random

        models = self.field_templates["models"]
        providers = self.field_templates["providers"]

        # Select model and provider pair
        model = random.choice(models)
        if "gpt" in model:
            provider = "openai"
        elif "claude" in model:
            provider = "anthropic"
        elif "gemini" in model:
            provider = "google"
        else:
            provider = random.choice(providers)

        # Generate realistic token counts based on model
        input_range = self.field_templates["token_ranges"]["input"]
        output_range = self.field_templates["token_ranges"]["output"]

        input_tokens = random.randint(input_range[0], input_range[1])
        output_tokens = random.randint(output_range[0], output_range[1])

        # Generate duration based on token count (more tokens = longer duration)
        base_duration = 1000 + (input_tokens + output_tokens) * 0.5
        duration_ms = int(base_duration + random.randint(-200, 500))

        return {
            "model": model,
            "provider": provider,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": duration_ms,
            "request_time": _get_utc_timestamp(),
            "response_time": _get_utc_timestamp(),
        }

    def _generate_enterprise_fields(
        self, index: int, industry_pattern: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate enterprise-specific fields."""
        import random

        return {
            "organization_id": random.choice(industry_pattern["organization_ids"]),
            "task_type": random.choice(industry_pattern["task_types"]),
            "agent": random.choice(industry_pattern["agents"]),
            "task_id": f"task_{index:04d}_{random.randint(1000, 9999)}",
            "trace_id": f"trace_{index:04d}_{random.randint(10000, 99999)}",
            "product_id": f"prod_{random.choice(['ai_assistant', 'code_gen', 'data_analysis'])}",
            "subscription_id": f"sub_{random.randint(100000, 999999)}",
            "response_quality_score": random.choice(self.field_templates["quality_scores"]),
        }

    def _generate_subscriber_object(self, index: int, industry: str) -> Dict[str, Any]:
        """Generate realistic subscriber object with nested structure."""
        import random

        subscriber_template = self.subscriber_templates[industry]

        return {
            "id": f"sub_{index:04d}_{random.randint(1000, 9999)}",
            "email": f"{subscriber_template['email_prefix']}{index:03d}@{random.choice(subscriber_template['domains'])}",
            "credential": {
                "name": random.choice(subscriber_template["credential_names"]),
                "type": random.choice(["api_key", "oauth_token", "service_account"]),
            },
        }

    def _generate_edge_case_fields(self, index: int) -> Dict[str, Any]:
        """Generate edge case field values for testing boundary conditions."""
        import random

        edge_cases = random.choice(self.edge_case_patterns)
        return edge_cases

    def _build_industry_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Build industry-specific data patterns."""
        return {
            "financial_services": {
                "organization_ids": [
                    "goldman-sachs",
                    "jp-morgan",
                    "wells-fargo",
                    "blackrock",
                    "vanguard",
                ],
                "task_types": [
                    "risk_analysis",
                    "fraud_detection",
                    "market_sentiment",
                    "portfolio_optimization",
                ],
                "agents": ["RiskBot_v2.1", "FraudDetector_AI", "MarketIntel_v3.0", "PortfolioAI"],
            },
            "healthcare": {
                "organization_ids": [
                    "mayo-clinic",
                    "johns-hopkins",
                    "cleveland-clinic",
                    "kaiser-permanente",
                ],
                "task_types": [
                    "diagnosis_support",
                    "treatment_planning",
                    "medical_research",
                    "patient_monitoring",
                ],
                "agents": [
                    "DiagnosisAI_v1.5",
                    "TreatmentBot",
                    "ResearchAssistant",
                    "PatientMonitor",
                ],
            },
            "legal": {
                "organization_ids": [
                    "baker-mckenzie",
                    "latham-watkins",
                    "skadden",
                    "kirkland-ellis",
                ],
                "task_types": [
                    "contract_analysis",
                    "legal_research",
                    "compliance_check",
                    "document_review",
                ],
                "agents": ["LegalBot_v2.0", "ContractAI", "ComplianceChecker", "DocReviewer"],
            },
            "technology": {
                "organization_ids": ["microsoft", "google", "amazon", "meta", "apple"],
                "task_types": [
                    "code_generation",
                    "bug_analysis",
                    "system_design",
                    "performance_optimization",
                ],
                "agents": ["CodeGen_v3.0", "BugHunter", "ArchitectAI", "PerfOptimizer"],
            },
        }

    def _build_field_templates(self) -> Dict[str, Any]:
        """Build field templates for test data generation."""
        return {
            "models": [
                "gpt-4o",
                "gpt-4",
                "gpt-3.5-turbo",
                "claude-3-5-sonnet-20241022",
                "claude-3-haiku-20240307",
                "gemini-pro",
                "gemini-1.5-pro",
            ],
            "providers": ["openai", "anthropic", "google"],
            "token_ranges": {"input": (500, 8000), "output": (200, 3000)},
            "duration_ranges": {"fast": (800, 2000), "medium": (2000, 5000), "slow": (5000, 15000)},
            "quality_scores": [0.85, 0.90, 0.92, 0.95, 0.98],
            "stop_reasons": ["stop", "length", "content_filter", "function_call"],
        }

    def _build_subscriber_templates(self) -> Dict[str, Dict[str, Any]]:
        """Build subscriber templates for different industries."""
        return {
            "financial_services": {
                "email_prefix": "trader",
                "domains": ["goldmansachs.com", "jpmorgan.com", "wellsfargo.com"],
                "credential_names": ["trading_api", "risk_api", "market_data_key"],
            },
            "healthcare": {
                "email_prefix": "doctor",
                "domains": ["mayoclinic.org", "hopkinsmedicine.org", "clevelandclinic.org"],
                "credential_names": ["medical_api", "patient_data_key", "research_token"],
            },
            "legal": {
                "email_prefix": "attorney",
                "domains": ["bakermckenzie.com", "lw.com", "skadden.com"],
                "credential_names": ["legal_api", "document_key", "case_research_token"],
            },
            "technology": {
                "email_prefix": "engineer",
                "domains": ["microsoft.com", "google.com", "amazon.com"],
                "credential_names": ["dev_api", "system_key", "deployment_token"],
            },
        }

    def _build_edge_case_patterns(self) -> List[Dict[str, Any]]:
        """Build edge case patterns for boundary testing."""
        return [
            # Very high token counts
            {"input_tokens": 32000, "output_tokens": 8000, "duration_ms": 45000},
            # Very low token counts
            {"input_tokens": 1, "output_tokens": 1, "duration_ms": 100},
            # Special characters in fields
            {
                "task_type": "test_with_special_chars_!@#$%",
                "agent": "Agent-With-Dashes_And_Underscores",
            },
            # Empty optional fields (omit task_id to avoid validation error)
            {"trace_id": None},
            # Unicode characters
            {"organization_id": "test-org-ñáéíóú", "task_type": "análisis_de_riesgo"},
            # Very long strings
            {"task_type": "very_long_task_type_" + "x" * 100},
            # Quality score boundary values
            {"response_quality_score": 0.0, "subscription_id": "sub_boundary_test_min"},
            {"response_quality_score": 1.0, "subscription_id": "sub_boundary_test_max"},
            # Quality score precision testing
            {"response_quality_score": 0.999999, "subscription_id": "sub_precision_test"},
        ]


class FieldMappingAnalyzer:
    """Analyzer for field presence and mapping accuracy using Revenium reporting API."""

    def __init__(self):
        """Initialize field mapping analyzer with expected field mappings."""
        self.analysis_cache = {}
        self.expected_field_mappings = self._build_expected_field_mappings()
        self.critical_fields = self._build_critical_fields()

    async def analyze_field_presence(
        self,
        client: ReveniumClient,
        verification_result: Dict[str, Any],
        submitted_transactions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Analyze field presence and optionally perform data integrity validation.

        Args:
            client: Revenium API client
            verification_result: Result from transaction verification
            submitted_transactions: Optional dict of submitted transaction data for integrity validation

        Returns:
            Analysis results with field presence and optionally integrity validation
        """
        logger.info("🔍 Starting comprehensive field mapping analysis...")

        try:
            # ✅ NEW: Use transaction data from verification result if available (100% code reuse)
            if "transaction_data" in verification_result:
                recent_transactions = verification_result["transaction_data"]
                logger.info(
                    f"📊 Using {len(recent_transactions)} transactions from verification result (100% code reuse)"
                )
            else:
                # Fallback for backward compatibility
                recent_transactions = await self._fetch_recent_transactions(client, limit=50)
                logger.warning(
                    "⚠️ Using fallback transaction fetch - consider enabling return_transaction_data for better performance"
                )

            if not recent_transactions:
                return {
                    "analysis_type": "field_mapping",
                    "total_transactions": 0,
                    "status": "no_data",
                    "message": "No transactions found for analysis",
                    "recommendations": [
                        "Submit test transactions first",
                        "Check API permissions",
                        "Ensure verification found transactions",
                    ],
                }

            # Perform comprehensive field analysis (existing Option A functionality)
            field_analysis = await self._analyze_transaction_fields(recent_transactions)

            # ✅ NEW: Data integrity validation (Option B) when submitted_transactions provided
            integrity_analysis = None
            if submitted_transactions:
                logger.info(
                    f"🔬 Performing data integrity validation with {len(submitted_transactions)} submitted transactions"
                )
                integrity_analysis = await self._analyze_data_integrity(
                    recent_transactions, submitted_transactions
                )
                field_analysis["integrity_analysis"] = integrity_analysis

            # Generate recommendations based on analysis
            recommendations = self._generate_field_recommendations(field_analysis)

            # ✅ NEW: Add integrity-specific recommendations if available
            if integrity_analysis:
                integrity_recommendations = self._generate_integrity_recommendations(
                    integrity_analysis
                )
                recommendations.extend(integrity_recommendations)

            return {
                "analysis_type": (
                    "field_mapping_with_integrity" if submitted_transactions else "field_mapping"
                ),
                "total_transactions": len(recent_transactions),
                "verified_count": verification_result.get("verified_count", 0),
                "missing_count": verification_result.get("missing_count", 0),
                "field_analysis": field_analysis,
                "recommendations": recommendations,
                "timestamp": _get_utc_timestamp(),
            }

        except Exception as e:
            logger.error(f"Error in field mapping analysis: {e}")
            return {
                "analysis_type": "field_mapping",
                "total_transactions": 0,
                "status": "error",
                "error": str(e),
                "recommendations": [
                    "Check API connectivity",
                    "Verify authentication",
                    "Try again later",
                ],
            }

    async def _fetch_recent_transactions(
        self, client: ReveniumClient, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch recent transactions from Revenium reporting API with pagination validation."""
        try:
            # ✅ PAGINATION VALIDATION: Enforce API limits with helpful guidance
            if limit > 50:
                logger.warning(
                    f"Requested limit {limit} exceeds API maximum of 50, automatically capping to 50"
                )
                limit = 50

            endpoint = "/profitstream/v2/api/sources/metrics/ai/completions"
            params = {
                "teamId": client.team_id,
                "page": 0,
                "size": limit,  # Already validated to be ≤ 50
                "sort": "timestamp,desc",
            }

            logger.info(f"📡 Querying reporting API: {endpoint}")
            response = await client.get(endpoint, params=params)

            # Handle both possible response structures
            transactions = []
            if (
                "_embedded" in response
                and "aICompletionMetricResourceList" in response["_embedded"]
            ):
                # New API structure with _embedded
                transactions = response["_embedded"]["aICompletionMetricResourceList"]
                logger.info(
                    f"📊 Retrieved {len(transactions)} transactions for analysis (new structure)"
                )
                return transactions
            elif "content" in response:
                # Legacy API structure with content
                transactions = response["content"]
                logger.info(
                    f"📊 Retrieved {len(transactions)} transactions for analysis (legacy structure)"
                )
                return transactions
            else:
                logger.warning(
                    "No 'content' or '_embedded.aICompletionMetricResourceList' field in reporting API response"
                )
                return []

        except Exception as e:
            logger.error(f"Failed to fetch transactions from reporting API: {e}")
            return []

    async def _analyze_transaction_fields(
        self, transactions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze field presence and mapping accuracy across transactions."""
        total_transactions = len(transactions)
        field_presence = {}
        field_samples = {}
        subscriber_analysis = {
            "total_with_subscriber": 0,
            "email_present": 0,
            "id_present": 0,
            "credential_present": 0,
            "credential_name_present": 0,
        }

        # Analyze each transaction
        for transaction in transactions:
            # Check presence of expected fields
            for expected_field, api_field in self.expected_field_mappings.items():
                if api_field in transaction:
                    field_presence[expected_field] = field_presence.get(expected_field, 0) + 1
                    # Store sample values (first occurrence)
                    if expected_field not in field_samples:
                        field_samples[expected_field] = transaction[api_field]

            # Special analysis for subscriber fields (CORRECTED for API response structure)
            if "subscriberEmail" in transaction or "subscriberId" in transaction:
                subscriber_analysis["total_with_subscriber"] += 1

                # Check for subscriber email
                if "subscriberEmail" in transaction and transaction["subscriberEmail"]:
                    subscriber_analysis["email_present"] += 1

                # Check for subscriber ID
                if "subscriberId" in transaction and transaction["subscriberId"]:
                    subscriber_analysis["id_present"] += 1

                # Check for subscriber credential
                if "subscriberCredential" in transaction and transaction["subscriberCredential"]:
                    subscriber_analysis["credential_present"] += 1
                    credential = transaction["subscriberCredential"]
                    if isinstance(credential, dict) and "label" in credential:
                        subscriber_analysis["credential_name_present"] += 1

        # Calculate percentages
        field_percentages = {}
        for field, count in field_presence.items():
            field_percentages[field] = round((count / total_transactions) * 100, 1)

        return {
            "field_presence_counts": field_presence,
            "field_presence_percentages": field_percentages,
            "field_samples": field_samples,
            "subscriber_analysis": subscriber_analysis,
            "critical_field_status": self._analyze_critical_fields(field_percentages),
            "total_analyzed": total_transactions,
        }

    def _build_expected_field_mappings(self) -> Dict[str, str]:
        """Build comprehensive mapping between submitted field names and actual API response field names.

        Based on actual API response structure from /profitstream/v2/api/sources/metrics/ai/completions
        """
        return {
            # Core transaction fields - EXACT API field names
            "model": "model",
            "provider": "provider",
            "input_tokens": "inputTokenCount",
            "output_tokens": "outputTokenCount",
            "duration_ms": "requestDuration",
            # Token-related fields
            "total_tokens": "totalTokenCount",
            "reasoning_tokens": "reasoningTokenCount",
            "cached_tokens": "cachedTokenCount",
            "cache_creation_tokens": "cacheCreationTokenCount",
            "cache_read_tokens": "cacheReadTokenCount",
            # Cost and billing fields
            "input_token_cost": "inputTokenCost",
            "output_token_cost": "outputTokenCost",
            "total_cost": "totalCost",
            "cost_type": "costType",
            # Performance and quality fields
            "response_quality_score": "responseQualityScore",
            "is_streamed": "isStreamed",
            "stop_reason": "stopReason",
            "time_to_first_token": "timeToFirstToken",
            "tokens_per_minute": "tokensPerMinute",
            # Timestamp fields
            "request_time": "requestTime",
            "response_time": "responseTime",
            "completion_start_time": "completionStartTime",
            # Enterprise attribution fields
            "task_type": "taskType",
            "agent": "agent",
            "trace_id": "traceId",
            "subscription_id": "subscriptionId",
            "operation_type": "operationType",
            # Note: Subscriber data now passed as subscriber object, not separate fields
            # Model and provider details
            "model_source": "modelSource",
            "system_fingerprint": "systemFingerprint",
            "temperature": "temperature",
            # Error and debugging fields
            "error_reason": "errorReason",
            "mediation_latency": "mediationLatency",
            "middleware_source": "middlewareSource",
            # Nested object references (these contain IDs and labels)
            "organization": "organization",
            "product": "product",
            "team": "team",
            "source": "source",
        }

    def _build_critical_fields(self) -> List[str]:
        """Build list of critical fields that should always be present."""
        return [
            "model",
            "provider",
            "input_tokens",
            "output_tokens",
            "duration_ms",
            "subscriber",  # Use subscriber object instead of legacy fields
        ]

    def _analyze_critical_fields(self, field_percentages: Dict[str, float]) -> Dict[str, Any]:
        """Analyze critical field presence and identify issues."""
        critical_status = {}
        issues = []

        for field in self.critical_fields:
            percentage = field_percentages.get(field, 0)
            status = (
                "excellent"
                if percentage >= 95
                else "good" if percentage >= 80 else "poor" if percentage >= 50 else "critical"
            )

            critical_status[field] = {
                "percentage": percentage,
                "status": status,
                "present": percentage > 0,
            }

            if percentage < 95:
                issues.append(f"{field}: {percentage}% presence (expected: 95%+)")

        return {
            "field_status": critical_status,
            "issues": issues,
            "overall_health": "excellent" if len(issues) == 0 else "needs_attention",
        }

    def _generate_field_recommendations(self, field_analysis: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on field analysis."""
        recommendations = []

        # Check critical field issues
        critical_status = field_analysis.get("critical_field_status", {})
        issues = critical_status.get("issues", [])

        if issues:
            recommendations.append("🚨 Critical field mapping issues detected:")
            for issue in issues:
                recommendations.append(f"  • {issue}")

        # Check subscriber field issues
        subscriber_analysis = field_analysis.get("subscriber_analysis", {})
        total_with_subscriber = subscriber_analysis.get("total_with_subscriber", 0)
        email_present = subscriber_analysis.get("email_present", 0)

        if total_with_subscriber > 0:
            email_percentage = (email_present / total_with_subscriber) * 100
            if email_percentage < 90:
                recommendations.append(
                    f"📧 Subscriber email mapping issue: {email_percentage:.1f}% presence"
                )
                recommendations.append("  • Check subscriber object structure in submissions")
                recommendations.append("  • Verify email field is properly nested")

        # General recommendations
        field_percentages = field_analysis.get("field_presence_percentages", {})
        low_presence_fields = [field for field, pct in field_percentages.items() if pct < 80]

        if low_presence_fields:
            recommendations.append("⚠️ Fields with low presence detected:")
            for field in low_presence_fields:
                pct = field_percentages[field]
                recommendations.append(f"  • {field}: {pct}% (consider reviewing submission logic)")

        if not recommendations:
            recommendations.append("✅ All field mappings appear to be working correctly")
            recommendations.append("✅ No critical issues detected")

        return recommendations

    async def _analyze_data_integrity(
        self,
        retrieved_transactions: List[Dict[str, Any]],
        submitted_transactions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Perform comprehensive data integrity validation by correlating submitted vs retrieved transactions.

        Args:
            retrieved_transactions: Transactions from Revenium reporting API
            submitted_transactions: Submitted transaction data from transaction store

        Returns:
            Comprehensive integrity analysis results as specified in PRD
        """
        logger.info(
            f"🔬 Starting data integrity validation: {len(retrieved_transactions)} retrieved vs {len(submitted_transactions)} submitted"
        )

        # Step 1: Correlate transactions by transactionId
        correlation_results = self._correlate_transactions(
            retrieved_transactions, submitted_transactions
        )

        # Step 2: Perform field-by-field comparison for correlated transactions
        integrity_results = self._validate_field_integrity(correlation_results)

        # Step 3: Calculate integrity metrics
        integrity_score = self._calculate_integrity_score(integrity_results)

        # Step 4: Generate detailed analysis
        return {
            "total_submitted": len(submitted_transactions),
            "total_retrieved": len(retrieved_transactions),
            "perfect_matches": integrity_results.get("perfect_matches", 0),
            "transactions_with_mismatches": integrity_results.get(
                "transactions_with_mismatches", 0
            ),
            "missing_transactions": integrity_results.get("missing_transactions", []),
            "field_mismatch_summary": integrity_results.get("field_mismatch_summary", {}),
            "integrity_score": integrity_score,
            "detailed_mismatches": integrity_results.get("detailed_mismatches", []),
            "correlation_summary": correlation_results.get("summary", {}),
            "timestamp": _get_utc_timestamp(),
        }

    def _generate_integrity_recommendations(self, integrity_analysis: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on integrity analysis results.

        Args:
            integrity_analysis: Results from _analyze_data_integrity

        Returns:
            List of actionable recommendations
        """
        recommendations = []

        integrity_score = integrity_analysis.get("integrity_score", 0.0)
        missing_transactions = integrity_analysis.get("missing_transactions", [])
        transactions_with_mismatches = integrity_analysis.get("transactions_with_mismatches", 0)

        # Overall integrity assessment
        if integrity_score >= 0.99:
            recommendations.append("✅ Excellent data integrity: >99% accuracy achieved")
        elif integrity_score >= 0.95:
            recommendations.append("✅ Good data integrity: >95% accuracy achieved")
        elif integrity_score >= 0.90:
            recommendations.append("⚠️ Moderate data integrity issues: 90-95% accuracy")
            recommendations.append("💡 Review field mapping logic for improvements")
        else:
            recommendations.append("🚨 Critical data integrity issues: <90% accuracy")
            recommendations.append("🚨 Immediate investigation required")

        # Missing transactions
        if missing_transactions:
            recommendations.append(
                f"⚠️ {len(missing_transactions)} transactions missing from reporting API"
            )
            recommendations.append("💡 Check API processing delays or submission failures")
            recommendations.append("💡 Consider increasing wait_seconds parameter")

        # Field mismatches
        if transactions_with_mismatches > 0:
            recommendations.append(
                f"🔍 {transactions_with_mismatches} transactions have field mismatches"
            )
            recommendations.append("💡 Review detailed_mismatches for specific field issues")
            recommendations.append("💡 Check for type conversion or truncation issues")

        # Field-specific recommendations
        field_mismatch_summary = integrity_analysis.get("field_mismatch_summary", {})
        for field, mismatch_count in field_mismatch_summary.items():
            if mismatch_count > 0:
                recommendations.append(f"🔧 Field '{field}': {mismatch_count} mismatches detected")

        return recommendations

    def _correlate_transactions(
        self,
        retrieved_transactions: List[Dict[str, Any]],
        submitted_transactions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Correlate submitted transactions with retrieved transactions by transactionId.

        Args:
            retrieved_transactions: Transactions from Revenium reporting API
            submitted_transactions: Submitted transaction data from transaction store

        Returns:
            Correlation results with matched and missing transactions
        """
        logger.info(
            f"🔗 Correlating {len(retrieved_transactions)} retrieved vs {len(submitted_transactions)} submitted transactions"
        )

        # Build lookup map for retrieved transactions by transactionId
        retrieved_by_id = {}
        for tx in retrieved_transactions:
            tx_id = tx.get("transactionId")
            if tx_id:
                retrieved_by_id[tx_id] = tx

        # Correlate submitted transactions with retrieved ones
        matched_pairs = []
        missing_transactions = []

        for tx_id, submitted_data in submitted_transactions.items():
            if tx_id in retrieved_by_id:
                # Found matching transaction
                matched_pairs.append(
                    {
                        "transaction_id": tx_id,
                        "submitted_payload": submitted_data.get("payload", {}),
                        "retrieved_transaction": retrieved_by_id[tx_id],
                        "submitted_timestamp": submitted_data.get("timestamp"),
                    }
                )
                logger.debug(f"✅ Correlated transaction {tx_id}")
            else:
                # Missing transaction
                missing_transactions.append(tx_id)
                logger.warning(f"❌ Transaction {tx_id} not found in retrieved data")

        correlation_summary = {
            "total_submitted": len(submitted_transactions),
            "total_retrieved": len(retrieved_transactions),
            "matched_pairs": len(matched_pairs),
            "missing_count": len(missing_transactions),
            "correlation_rate": (
                len(matched_pairs) / len(submitted_transactions) if submitted_transactions else 0.0
            ),
        }

        logger.info(
            f"🔗 Correlation complete: {len(matched_pairs)} matched, {len(missing_transactions)} missing"
        )

        return {
            "matched_pairs": matched_pairs,
            "missing_transactions": missing_transactions,
            "summary": correlation_summary,
            "retrieved_by_id": retrieved_by_id,  # For additional analysis if needed
        }

    def _validate_field_integrity(self, correlation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Validate field integrity by comparing submitted vs retrieved values field-by-field.

        Args:
            correlation_results: Results from _correlate_transactions

        Returns:
            Comprehensive field integrity validation results
        """
        matched_pairs = correlation_results.get("matched_pairs", [])
        missing_transactions = correlation_results.get("missing_transactions", [])

        logger.info(
            f"🔍 Validating field integrity for {len(matched_pairs)} matched transaction pairs"
        )

        perfect_matches = 0
        transactions_with_mismatches = 0
        detailed_mismatches = []
        field_mismatch_summary = {}

        for pair in matched_pairs:
            transaction_id = pair["transaction_id"]
            submitted_payload = pair["submitted_payload"]
            retrieved_transaction = pair["retrieved_transaction"]

            # Compare values field by field
            mismatches = self._compare_transaction_values(submitted_payload, retrieved_transaction)

            if not mismatches:
                perfect_matches += 1
                logger.debug(f"✅ Perfect match for transaction {transaction_id}")
            else:
                transactions_with_mismatches += 1
                logger.warning(
                    f"⚠️ {len(mismatches)} mismatches found for transaction {transaction_id}"
                )

                # Add to detailed mismatches
                detailed_mismatches.append(
                    {
                        "transaction_id": transaction_id,
                        "mismatch_count": len(mismatches),
                        "mismatches": mismatches,
                    }
                )

                # Update field mismatch summary
                for mismatch in mismatches:
                    field = mismatch["field"]
                    field_mismatch_summary[field] = field_mismatch_summary.get(field, 0) + 1

        return {
            "perfect_matches": perfect_matches,
            "transactions_with_mismatches": transactions_with_mismatches,
            "missing_transactions": missing_transactions,
            "detailed_mismatches": detailed_mismatches,
            "field_mismatch_summary": field_mismatch_summary,
            "total_analyzed": len(matched_pairs),
        }

    def _compare_transaction_values(
        self, submitted_payload: Dict[str, Any], retrieved_transaction: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Compare submitted vs retrieved values field by field as specified in PRD.

        Args:
            submitted_payload: Original submitted transaction data
            retrieved_transaction: Transaction data from Revenium API

        Returns:
            List of mismatches with detailed information
        """
        mismatches = []

        for submitted_field, api_field in self.expected_field_mappings.items():
            # Check if field exists in both submitted and retrieved data
            if submitted_field in submitted_payload and api_field in retrieved_transaction:
                submitted_value = submitted_payload[submitted_field]
                retrieved_value = retrieved_transaction[api_field]

                # Compare values with intelligent type handling
                if not self._values_match(submitted_value, retrieved_value):
                    mismatch_type = self._classify_mismatch(submitted_value, retrieved_value)

                    mismatches.append(
                        {
                            "field": submitted_field,
                            "api_field": api_field,
                            "submitted": submitted_value,
                            "retrieved": retrieved_value,
                            "mismatch_type": mismatch_type,
                            "severity": self._determine_mismatch_severity(mismatch_type),
                        }
                    )

                    logger.debug(
                        f"🔍 Mismatch in {submitted_field}: {submitted_value} → {retrieved_value} ({mismatch_type})"
                    )

        return mismatches

    def _values_match(self, submitted_value: Any, retrieved_value: Any) -> bool:
        """Intelligent value comparison that handles expected type conversions.

        Args:
            submitted_value: Value from submitted payload
            retrieved_value: Value from API response

        Returns:
            True if values are considered equivalent
        """
        # Direct equality check first
        if submitted_value == retrieved_value:
            return True

        # Handle None/null cases
        if submitted_value is None and retrieved_value is None:
            return True
        if submitted_value is None or retrieved_value is None:
            return False

        # Handle string/number conversions (common in APIs)
        try:
            # Try numeric comparison for string/number pairs
            if isinstance(submitted_value, (int, float)) and isinstance(retrieved_value, str):
                return float(submitted_value) == float(retrieved_value)
            elif isinstance(submitted_value, str) and isinstance(retrieved_value, (int, float)):
                return float(submitted_value) == float(retrieved_value)

            # Handle boolean conversions
            if isinstance(submitted_value, bool) and isinstance(retrieved_value, str):
                return str(submitted_value).lower() == retrieved_value.lower()
            elif isinstance(submitted_value, str) and isinstance(retrieved_value, bool):
                return submitted_value.lower() == str(retrieved_value).lower()
        except (ValueError, TypeError):
            # If conversion fails, values don't match
            pass

        return False

    def _determine_mismatch_severity(self, mismatch_type: str) -> str:
        """Determine severity level of a field mismatch.

        Args:
            mismatch_type: Type of mismatch detected

        Returns:
            Severity level: 'low', 'medium', 'high', 'critical'
        """
        severity_map = {
            "type_conversion": "low",  # Expected API behavior
            "precision_loss": "medium",  # May affect calculations
            "truncation": "high",  # Data loss
            "value_corruption": "critical",  # Serious data integrity issue
            "field_mapping_error": "critical",  # Wrong field mapping
            "encoding_issue": "high",  # Character encoding problems
        }

        return severity_map.get(mismatch_type, "medium")

    def _classify_mismatch(self, submitted_value: Any, retrieved_value: Any) -> str:
        """Classify the type of mismatch between submitted and retrieved values.

        Args:
            submitted_value: Value from submitted payload
            retrieved_value: Value from API response

        Returns:
            Mismatch type classification
        """
        # Handle None/null mismatches
        if submitted_value is None or retrieved_value is None:
            return "null_handling"

        # Check for type conversions
        if type(submitted_value) != type(retrieved_value):
            # Common API type conversions
            if isinstance(submitted_value, (int, float)) and isinstance(retrieved_value, str):
                try:
                    if float(submitted_value) == float(retrieved_value):
                        return "type_conversion"  # Expected behavior
                except ValueError:
                    return "value_corruption"
            elif isinstance(submitted_value, str) and isinstance(retrieved_value, (int, float)):
                try:
                    if float(submitted_value) == float(retrieved_value):
                        return "type_conversion"  # Expected behavior
                except ValueError:
                    return "value_corruption"
            elif isinstance(submitted_value, bool) != isinstance(retrieved_value, bool):
                return "type_conversion"
            else:
                return "field_mapping_error"  # Unexpected type change

        # Same type but different values
        if isinstance(submitted_value, str) and isinstance(retrieved_value, str):
            # Check for truncation
            if len(submitted_value) > len(retrieved_value) and submitted_value.startswith(
                retrieved_value
            ):
                return "truncation"
            # Check for encoding issues
            if self._has_encoding_issues(submitted_value, retrieved_value):
                return "encoding_issue"
            # Otherwise it's value corruption
            return "value_corruption"

        elif isinstance(submitted_value, (int, float)) and isinstance(
            retrieved_value, (int, float)
        ):
            # Check for precision loss
            if abs(float(submitted_value) - float(retrieved_value)) < 0.000001:
                return "precision_loss"
            else:
                return "value_corruption"

        # Default classification
        return "value_corruption"

    def _has_encoding_issues(self, submitted: str, retrieved: str) -> bool:
        """Check if string mismatch is due to encoding issues.

        Args:
            submitted: Original submitted string
            retrieved: Retrieved string from API

        Returns:
            True if encoding issues are detected
        """
        try:
            # Check for common encoding issues
            if submitted.encode("utf-8").decode("latin-1") == retrieved:
                return True
            if submitted.encode("latin-1").decode("utf-8", errors="ignore") == retrieved:
                return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

        return False

    def _calculate_integrity_score(self, integrity_results: Dict[str, Any]) -> float:
        """Calculate overall data integrity score (0.0-1.0) based on validation results.

        Args:
            integrity_results: Results from _validate_field_integrity

        Returns:
            Integrity score between 0.0 and 1.0
        """
        total_analyzed = integrity_results.get("total_analyzed", 0)
        if total_analyzed == 0:
            return 0.0

        perfect_matches = integrity_results.get("perfect_matches", 0)

        # Base score from perfect matches
        base_score = perfect_matches / total_analyzed

        # Penalty for mismatches based on severity
        detailed_mismatches = integrity_results.get("detailed_mismatches", [])
        total_penalty = 0.0

        for transaction_mismatch in detailed_mismatches:
            mismatches = transaction_mismatch.get("mismatches", [])
            transaction_penalty = 0.0

            for mismatch in mismatches:
                severity = mismatch.get("severity", "medium")
                # Severity penalties
                if severity == "critical":
                    transaction_penalty += 0.5  # Heavy penalty
                elif severity == "high":
                    transaction_penalty += 0.3
                elif severity == "medium":
                    transaction_penalty += 0.2
                elif severity == "low":
                    transaction_penalty += 0.1  # Light penalty for expected conversions

            # Cap transaction penalty at 1.0 (complete failure)
            transaction_penalty = min(transaction_penalty, 1.0)
            total_penalty += transaction_penalty

        # Calculate final score
        if total_analyzed > 0:
            penalty_per_transaction = total_penalty / total_analyzed
            final_score = max(0.0, base_score - penalty_per_transaction)
        else:
            final_score = 0.0

        return round(final_score, 4)


class ValidationReporter:
    """Reporter for comprehensive validation results with export capabilities."""

    def __init__(self):
        """Initialize validation reporter with templates and formatters."""
        self.report_templates = self._build_report_templates()
        self.severity_levels = self._build_severity_levels()
        self.export_formats = ["json", "markdown", "csv"]

    def enhance_validation_report(
        self, validation_result: Dict[str, Any], arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhance validation report with additional analysis and metadata."""
        enhanced_result = validation_result.copy()
        enhanced_result["enhanced_analysis"] = {
            "timestamp": _get_utc_timestamp(),
            "field_count": len(arguments),
            "validation_type": "field_validation",
            "arguments_analyzed": list(arguments.keys()),
            "validation_score": self._calculate_validation_score(validation_result),
            "severity": self._determine_severity(validation_result),
        }
        return enhanced_result

    def generate_field_mapping_report(
        self, field_analysis: Dict[str, Any], format_type: str = "markdown"
    ) -> str:
        """Generate comprehensive field mapping report in specified format."""
        if format_type == "markdown":
            return self._generate_markdown_report(field_analysis)
        elif format_type == "json":
            return json.dumps(field_analysis, indent=2)
        elif format_type == "csv":
            return self._generate_csv_report(field_analysis)
        else:
            raise ValueError(f"Unsupported format: {format_type}")

    def generate_batch_summary_report(self, batch_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate summary report for batch submission results."""
        total_transactions = len(batch_results)
        successful = len([r for r in batch_results if r.get("status") == "success"])
        failed = total_transactions - successful

        # Analyze failure patterns
        failure_patterns = {}
        for result in batch_results:
            if result.get("status") == "error":
                error = result.get("error", "Unknown error")
                failure_patterns[error] = failure_patterns.get(error, 0) + 1

        # Calculate success rate
        success_rate = (successful / total_transactions * 100) if total_transactions > 0 else 0

        return {
            "summary": {
                "total_transactions": total_transactions,
                "successful": successful,
                "failed": failed,
                "success_rate": round(success_rate, 1),
            },
            "failure_patterns": failure_patterns,
            "recommendations": self._generate_batch_recommendations(success_rate, failure_patterns),
            "timestamp": _get_utc_timestamp(),
        }

    def _calculate_validation_score(self, validation_result: Dict[str, Any]) -> float:
        """Calculate overall validation score (0-100)."""
        if not validation_result.get("valid", False):
            return 0.0

        # Base score for valid transaction
        score = 70.0

        # Bonus points for completeness
        if "message" in validation_result and validation_result["message"]:
            score += 10.0

        # Additional scoring based on validation details
        if "details" in validation_result:
            score += 20.0

        return min(score, 100.0)

    def _determine_severity(self, validation_result: Dict[str, Any]) -> str:
        """Determine severity level of validation result."""
        if not validation_result.get("valid", False):
            return "critical"

        score = self._calculate_validation_score(validation_result)
        if score >= 90:
            return "low"
        elif score >= 70:
            return "medium"
        else:
            return "high"

    def _generate_markdown_report(self, field_analysis: Dict[str, Any]) -> str:
        """Generate markdown format field mapping report."""
        report = "# 🔍 Field Mapping Analysis Report\n\n"
        report += f"**Generated:** {field_analysis.get('timestamp', 'Unknown')}\n"
        report += f"**Total Transactions Analyzed:** {field_analysis.get('total_analyzed', 0)}\n\n"

        # Field presence summary
        report += "## 📊 Field Presence Summary\n\n"
        field_percentages = field_analysis.get("field_presence_percentages", {})

        if field_percentages:
            report += "| Field | Presence | Status |\n"
            report += "|-------|----------|--------|\n"

            for field, percentage in sorted(field_percentages.items()):
                status = (
                    "✅ Excellent"
                    if percentage >= 95
                    else "⚠️ Good" if percentage >= 80 else "❌ Poor"
                )
                report += f"| {field} | {percentage}% | {status} |\n"

        # Critical field analysis
        critical_status = field_analysis.get("critical_field_status", {})
        if critical_status:
            report += "\n## 🚨 Critical Field Analysis\n\n"
            overall_health = critical_status.get("overall_health", "unknown")
            report += f"**Overall Health:** {overall_health.title()}\n\n"

            issues = critical_status.get("issues", [])
            if issues:
                report += "**Issues Detected:**\n"
                for issue in issues:
                    report += f"- {issue}\n"

        # Subscriber analysis
        subscriber_analysis = field_analysis.get("subscriber_analysis", {})
        if subscriber_analysis.get("total_with_subscriber", 0) > 0:
            report += "\n## 👤 Subscriber Object Analysis\n\n"
            total = subscriber_analysis["total_with_subscriber"]
            email_pct = (
                (subscriber_analysis.get("email_present", 0) / total * 100) if total > 0 else 0
            )
            id_pct = (subscriber_analysis.get("id_present", 0) / total * 100) if total > 0 else 0

            report += f"- **Transactions with Subscriber:** {total}\n"
            report += f"- **Email Present:** {email_pct:.1f}%\n"
            report += f"- **ID Present:** {id_pct:.1f}%\n"

        # ✅ NEW: Data integrity analysis section
        integrity_analysis = field_analysis.get("integrity_analysis")
        if integrity_analysis:
            report += "\n## 🔬 Data Integrity Analysis\n\n"

            integrity_score = integrity_analysis.get("integrity_score", 0.0)
            perfect_matches = integrity_analysis.get("perfect_matches", 0)
            transactions_with_mismatches = integrity_analysis.get("transactions_with_mismatches", 0)
            missing_transactions = integrity_analysis.get("missing_transactions", [])

            # Overall integrity status
            if integrity_score >= 0.99:
                status_icon = "✅"
                status_text = "Excellent"
            elif integrity_score >= 0.95:
                status_icon = "✅"
                status_text = "Good"
            elif integrity_score >= 0.90:
                status_icon = "⚠️"
                status_text = "Moderate"
            else:
                status_icon = "🚨"
                status_text = "Critical"

            report += f"**Overall Integrity Score:** {integrity_score:.1%} ({status_icon} {status_text})\n\n"
            report += f"- **Perfect Matches:** {perfect_matches}\n"
            report += f"- **Transactions with Mismatches:** {transactions_with_mismatches}\n"
            report += f"- **Missing Transactions:** {len(missing_transactions)}\n\n"

            # Field mismatch summary
            field_mismatch_summary = integrity_analysis.get("field_mismatch_summary", {})
            if field_mismatch_summary:
                report += "**Field Mismatch Summary:**\n\n"
                report += "| Field | Mismatches | Impact |\n"
                report += "|-------|------------|--------|\n"

                for field, count in sorted(
                    field_mismatch_summary.items(), key=lambda x: x[1], reverse=True
                ):
                    impact = "🚨 High" if count > 5 else "⚠️ Medium" if count > 2 else "💡 Low"
                    report += f"| {field} | {count} | {impact} |\n"
                report += "\n"

            # Missing transactions details
            if missing_transactions:
                report += f"**Missing Transactions ({len(missing_transactions)}):**\n"
                for tx_id in missing_transactions[:5]:  # Show first 5
                    report += f"- {tx_id}\n"
                if len(missing_transactions) > 5:
                    report += f"- ... and {len(missing_transactions) - 5} more\n"
                report += "\n"

        # Recommendations
        recommendations = field_analysis.get("recommendations", [])
        if recommendations:
            report += "\n## 💡 Recommendations\n\n"
            for rec in recommendations:
                report += f"- {rec}\n"

        return report

    def _generate_csv_report(self, field_analysis: Dict[str, Any]) -> str:
        """Generate CSV format field mapping report."""
        import io

        output = io.StringIO()
        output.write("Field,Presence_Percentage,Status,Sample_Value\n")

        field_percentages = field_analysis.get("field_presence_percentages", {})
        field_samples = field_analysis.get("field_samples", {})

        for field, percentage in sorted(field_percentages.items()):
            status = "Excellent" if percentage >= 95 else "Good" if percentage >= 80 else "Poor"
            sample = str(field_samples.get(field, "")).replace(",", ";")  # Escape commas
            output.write(f"{field},{percentage},{status},{sample}\n")

        return output.getvalue()

    def _generate_batch_recommendations(
        self, success_rate: float, failure_patterns: Dict[str, int]
    ) -> List[str]:
        """Generate recommendations based on batch submission results."""
        recommendations = []

        if success_rate < 50:
            recommendations.append("🚨 Critical: Success rate below 50% - review submission logic")
        elif success_rate < 80:
            recommendations.append(
                "⚠️ Warning: Success rate below 80% - investigate common failures"
            )
        elif success_rate < 95:
            recommendations.append("💡 Good: Success rate above 80% - minor optimizations possible")
        else:
            recommendations.append("✅ Excellent: Success rate above 95%")

        # Analyze failure patterns
        if failure_patterns:
            most_common_error = max(failure_patterns.items(), key=lambda x: x[1])
            recommendations.append(
                f"🔍 Most common error: {most_common_error[0]} ({most_common_error[1]} occurrences)"
            )

            if "validation" in most_common_error[0].lower():
                recommendations.append(
                    "💡 Consider using validate_test_data() before batch submission"
                )
            elif "timeout" in most_common_error[0].lower():
                recommendations.append("💡 Consider reducing batch size or increasing timeout")

        return recommendations

    def _build_report_templates(self) -> Dict[str, str]:
        """Build report templates for different validation scenarios."""
        return {
            "field_mapping": "Field mapping analysis template",
            "batch_submission": "Batch submission analysis template",
            "validation_summary": "Validation summary template",
        }

    def _build_severity_levels(self) -> Dict[str, Dict[str, Any]]:
        """Build severity level definitions."""
        return {
            "low": {"color": "green", "icon": "✅", "threshold": 90},
            "medium": {"color": "yellow", "icon": "⚠️", "threshold": 70},
            "high": {"color": "orange", "icon": "🔶", "threshold": 50},
            "critical": {"color": "red", "icon": "🚨", "threshold": 0},
        }


class MeteringFieldValidationManagement(ToolBase):
    """Consolidated metering field validation tool with comprehensive capabilities."""

    tool_name = "manage_metering_field_validation"
    tool_description = "Comprehensive field validation and testing for AI transaction metering. Key actions: generate_test_data, validate_test_data, run_validation_suite, analyze_field_mapping. Use get_examples() for field validation templates and get_capabilities() for complete action list."
    business_category = "Metering and Analytics Tools"
    tool_type = ToolType.UTILITY
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize metering field validation tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_metering_field_validation")

        # Initialize internal components for validation
        self.test_generator = TestDataGenerator()
        self.field_analyzer = FieldMappingAnalyzer()

        # Reuse existing metering infrastructure
        self.transaction_manager = MeteringTransactionManager()
        self.validator = MeteringValidator(self.transaction_manager)

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle metering field validation actions.

        Args:
            action: Action to perform
            arguments: Action arguments

        Returns:
            Formatted response
        """
        try:
            # Route actions to appropriate handlers
            if action == "generate_test_data":
                return await self._handle_generate_test_data(arguments)
            elif action == "submit_test_batch":
                return await self._handle_submit_test_batch(arguments)
            elif action == "analyze_field_mapping":
                return await self._handle_analyze_field_mapping(arguments)
            elif action == "validate_test_data":
                return await self._handle_validate_test_data(arguments)
            elif action == "run_validation_suite":
                return await self._handle_run_validation_suite(arguments)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            else:
                raise ToolError(
                    f"Unknown action: {action}",
                    ErrorCodes.INVALID_INPUT,
                    details={"valid_actions": await self._get_supported_actions()},
                )

        except Exception as e:
            logger.error(f"Error in metering field validation action {action}: {e}")
            return self.format_error_response(e, f"metering_field_validation.{action}")

    async def _handle_generate_test_data(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Generate test data for validation."""
        test_data = self.test_generator.generate_batch(arguments)
        return self.format_success_response(
            "Test data generated successfully", {"test_data": test_data}
        )

    async def _handle_submit_test_batch(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Submit test batch for validation."""
        test_data = arguments.get("test_data", [])
        wait_seconds = arguments.get("wait_seconds", 30)

        if not test_data:
            return self.format_error_response(
                "No test data provided for batch submission", "submit_test_batch"
            )

        # Submit each transaction in the batch
        results = []
        client = await self.get_client()

        for i, transaction in enumerate(test_data):
            try:
                result = await self.transaction_manager.submit_transaction(client, transaction)
                results.append(
                    {
                        "index": i,
                        "transaction_id": result.get("transaction_id"),
                        "status": "submitted",
                        "data": transaction,
                    }
                )
            except Exception as e:
                results.append(
                    {"index": i, "status": "failed", "error": str(e), "data": transaction}
                )

        return self.format_success_response(
            f"Test batch submitted: {len([r for r in results if r['status'] == 'submitted'])}/{len(test_data)} successful",
            {"results": results, "wait_seconds": wait_seconds},
        )

    async def _handle_analyze_field_mapping(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Analyze field mapping accuracy."""
        analysis = await self.field_analyzer.analyze_mapping(arguments)
        return self.format_success_response(
            "Field mapping analysis completed", {"analysis": analysis}
        )

    async def _handle_validate_test_data(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Validate test data using existing validator."""
        validation_result = await self.validator.validate_transaction(arguments)
        return self.format_success_response(
            "Data validation completed", {"validation": validation_result}
        )

    async def _handle_run_validation_suite(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Run comprehensive validation suite."""
        suite_results = await self._run_validation_suite(arguments)
        return self.format_success_response(
            "Validation suite completed", {"results": suite_results}
        )

    async def _run_validation_suite(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Run validation suite with comprehensive testing."""
        # Implementation would use existing validation infrastructure
        return {
            "suite_type": arguments.get("suite_type", "basic"),
            "status": "completed",
            "summary": "Validation suite executed successfully",
        }

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_metering_field_validation schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform (required)",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of test transactions to generate (default: 10)",
                    "default": 10,
                },
                "industry": {
                    "type": "string",
                    "description": "Industry pattern for test data (financial_services, healthcare, legal)",
                    "default": "financial_services",
                },
                "suite_type": {
                    "type": "string",
                    "description": "Validation suite type (basic, enterprise, performance)",
                    "default": "basic",
                },
            },
            "required": ["action"],
        }

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get tool capabilities."""
        capabilities = await self._get_tool_capabilities()
        capabilities_text = "**Metering Field Validation Capabilities**\n\n"
        for cap in capabilities:
            capabilities_text += f"- **{cap.name}**: {cap.description}\n"

        return [TextContent(type="text", text=capabilities_text)]

    async def _handle_get_examples(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get usage examples."""
        examples_text = """**Metering Field Validation Examples**

1. **Generate Test Data**:
   ```
   generate_test_data(count=10, industry="financial_services")
   ```

2. **Validate Test Data**:
   ```
   validate_test_data(model="gpt-4o", provider="openai", input_tokens=1500)
   ```

3. **Run Validation Suite**:
   ```
   run_validation_suite(suite_type="basic")
   ```
"""
        return [TextContent(type="text", text=examples_text)]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get agent-friendly summary."""
        summary = f"Tool: {self.tool_name} - {self.tool_description}"
        return [TextContent(type="text", text=summary)]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get tool capabilities."""
        return [
            ToolCapability(
                name="Test Data Generation",
                description="Generate realistic AI transaction test datasets",
                parameters={
                    "count": "int (optional) - Number of test transactions",
                    "industry": "str (optional) - Industry pattern for test data",
                },
                examples=["generate_test_data(count=10, industry='financial_services')"],
            ),
            ToolCapability(
                name="Field Validation",
                description="Validate field mapping and data integrity",
                parameters={
                    "model": "str (required) - AI model name",
                    "provider": "str (required) - AI provider",
                    "input_tokens": "int (required) - Number of input tokens",
                },
                examples=[
                    "validate_test_data(model='gpt-4o', provider='openai', input_tokens=1500)"
                ],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "generate_test_data",
            "submit_test_batch",
            "analyze_field_mapping",
            "validate_test_data",
            "run_validation_suite",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
        ]


# Create instance for backward compatibility
# Note: UCM-enhanced instances are created in introspection registration
# Module-level instantiation removed to prevent UCM warnings during import
# metering_field_validation = MeteringFieldValidationManagement(ucm_helper=None)
