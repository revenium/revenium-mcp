"""Capability verification framework for the Unified Capability Manager.

This module provides API-based verification of capabilities to ensure they work
with the actual Revenium API endpoints.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger(__name__)

from ..client import ReveniumClient


class CapabilityVerifier:
    """Verifies capabilities against actual API endpoints."""

    def __init__(self, client: ReveniumClient):
        """Initialize the capability verifier.

        Args:
            client: Revenium API client for verification
        """
        self.client = client

        # Circuit breaker pattern for API failures
        self._api_failure_count = 0
        self._max_failures = 3
        self._circuit_open_until = None
        self._circuit_timeout = 300  # 5 minutes

        # Multi-level caching for API-discovered capabilities (OPTIMIZED)
        self._l1_cache: Dict[str, Dict[str, Any]] = (
            {}
        )  # In-memory, 2-minute TTL (reduced for performance)
        self._l2_cache: Dict[str, Dict[str, Any]] = (
            {}
        )  # Persistent, 15-minute TTL (reduced for performance)
        self._l3_cache: Dict[str, Dict[str, Any]] = (
            {}
        )  # Historical, 1-hour TTL (reduced for performance)
        self._cache_timestamps: Dict[str, float] = {}

        # Cache TTL settings (in seconds) - OPTIMIZED for performance
        self._l1_ttl = 120  # 2 minutes (reduced for faster refresh)
        self._l2_ttl = 900  # 15 minutes (reduced for performance)
        self._l3_ttl = 3600  # 1 hour (reduced for performance)

        # Define verification strategies for different capability types
        # STATIC ENUMS: Skip verification for hardcoded enum values (trust the enum definitions)
        # DYNAMIC CAPABILITIES: Verify against API for values discovered from endpoints
        self.verification_strategies = {
            # STATIC ENUMS - No verification needed (trust enum definitions)
            # "currencies": self._verify_currency_capability,  # DISABLED: Static enum
            # "plan_types": self._verify_plan_type_capability,  # DISABLED: Static enum
            # "billing_periods": self._verify_billing_period_capability,  # DISABLED: Static enum
            # "trial_periods": self._verify_trial_period_capability,  # DISABLED: Static enum
            # "payment_sources": self._verify_payment_source_capability,  # DISABLED: Static enum
            # "aggregation_types": self._verify_aggregation_type_capability,  # DISABLED: Static enum
            # "rating_aggregation_types": self._verify_rating_aggregation_type_capability,  # DISABLED: Static enum
            # DYNAMIC CAPABILITIES - Verify against API
            "user_roles": self._verify_user_role_capability,
            "organization_types": self._verify_organization_type_capability,
            "alert_types": self._verify_alert_type_capability,
            "metrics": self._verify_metric_capability,
            "operators": self._verify_operator_capability,
            "source_types": self._verify_source_type_capability,
            "element_types": self._verify_element_type_capability,
            "providers": self._verify_provider_capability,
            "models": self._verify_model_capability,
        }

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self._circuit_open_until is None:
            return False

        import time

        if time.time() < self._circuit_open_until:
            return True

        # Circuit timeout expired, reset
        self._circuit_open_until = None
        self._api_failure_count = 0
        return False

    def _record_api_failure(self):
        """Record an API failure and potentially open circuit."""
        self._api_failure_count += 1
        if self._api_failure_count >= self._max_failures:
            self._circuit_open_until = time.time() + self._circuit_timeout
            logger.warning(
                f"Circuit breaker opened due to {self._api_failure_count} failures. "
                f"Will remain open for {self._circuit_timeout} seconds."
            )
            # Clear L1 cache when circuit opens to force fallback to historical data
            self._l1_cache.clear()
            logger.info("Cleared L1 cache due to circuit breaker opening")

    def _record_api_success(self):
        """Record an API success and reset failure count."""
        self._api_failure_count = 0
        if self._circuit_open_until:
            self._circuit_open_until = None
            logger.info("Circuit breaker closed after successful API call")

    def _get_cache_key(self, capability_type: str, resource_type: str = "default") -> str:
        """Generate cache key for capability type."""
        return f"{resource_type}:{capability_type}"

    def _is_cache_valid(self, cache_key: str, ttl: int) -> bool:
        """Check if cache entry is still valid."""
        if cache_key not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[cache_key] < ttl

    def _get_cached_capabilities(
        self, capability_type: str, resource_type: str = "default"
    ) -> Optional[Set[str]]:
        """Get cached capabilities with TTL checking."""
        cache_key = self._get_cache_key(capability_type, resource_type)

        # Check L1 cache (5 minutes)
        if self._is_cache_valid(cache_key, self._l1_ttl) and cache_key in self._l1_cache:
            logger.debug(f"L1 cache hit for {cache_key}")
            return set(self._l1_cache[cache_key].get("values", []))

        # Check L2 cache (1 hour)
        if self._is_cache_valid(cache_key, self._l2_ttl) and cache_key in self._l2_cache:
            logger.debug(f"L2 cache hit for {cache_key}")
            # Promote to L1 cache
            self._l1_cache[cache_key] = self._l2_cache[cache_key]
            self._cache_timestamps[cache_key] = time.time()
            return set(self._l2_cache[cache_key].get("values", []))

        # Check L3 cache (24 hours) - historical data
        if self._is_cache_valid(cache_key, self._l3_ttl) and cache_key in self._l3_cache:
            logger.debug(f"L3 cache hit for {cache_key} (historical data)")
            return set(self._l3_cache[cache_key].get("values", []))

        return None

    def _cache_capabilities(
        self, capability_type: str, values: Set[str], resource_type: str = "default"
    ) -> None:
        """Cache discovered capabilities in all cache levels."""
        cache_key = self._get_cache_key(capability_type, resource_type)
        cache_data = {"values": list(values), "discovered_at": time.time()}

        # Store in all cache levels
        self._l1_cache[cache_key] = cache_data
        self._l2_cache[cache_key] = cache_data
        self._l3_cache[cache_key] = cache_data
        self._cache_timestamps[cache_key] = time.time()

        logger.debug(f"Cached {len(values)} values for {cache_key}")

    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status for monitoring."""
        return {
            "is_open": self._is_circuit_open(),
            "failure_count": self._api_failure_count,
            "max_failures": self._max_failures,
            "circuit_open_until": self._circuit_open_until,
            "timeout_seconds": self._circuit_timeout,
            "cache_stats": {
                "l1_entries": len(self._l1_cache),
                "l2_entries": len(self._l2_cache),
                "l3_entries": len(self._l3_cache),
            },
        }

    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker (for admin/testing purposes)."""
        self._api_failure_count = 0
        self._circuit_open_until = None
        logger.info("Circuit breaker manually reset")

    def clear_all_caches(self) -> None:
        """Clear all capability caches (for admin/testing purposes)."""
        self._l1_cache.clear()
        self._l2_cache.clear()
        self._l3_cache.clear()
        self._cache_timestamps.clear()
        logger.info("All capability caches cleared")

    async def _discover_capabilities_from_api(
        self, capability_type: str, endpoint: str, field_path: str, resource_type: str = "default"
    ) -> Set[str]:
        """Discover capabilities by parsing API responses."""
        try:
            # Make API call to discover capabilities
            response = await self.client.get(endpoint, params={"page": 0, "size": 50})
            self._record_api_success()

            discovered_values = set()

            # Parse response to extract capability values
            if "data" in response and isinstance(response["data"], list):
                for item in response["data"]:
                    # Navigate field path (e.g., "plan.currency")
                    value = item
                    for field in field_path.split("."):
                        if isinstance(value, dict) and field in value:
                            value = value[field]
                        else:
                            value = None
                            break

                    if value and isinstance(value, str):
                        discovered_values.add(value)

            if discovered_values:
                logger.info(
                    f"Discovered {len(discovered_values)} {capability_type} values from API: {discovered_values}"
                )
                # Cache the discovered values
                self._cache_capabilities(capability_type, discovered_values, resource_type)
                return discovered_values
            else:
                logger.warning(f"No {capability_type} values discovered from {endpoint}")
                return set()

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Failed to discover {capability_type} from {endpoint}: {e}")
            return set()

    async def verify_capabilities(
        self, resource_type: str, capabilities: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Verify all capabilities for a resource type.

        Args:
            resource_type: Type of resource (products, subscriptions, etc.)
            capabilities: Capabilities to verify

        Returns:
            Dictionary of verified capabilities
        """
        logger.info(f"Verifying capabilities for {resource_type}")
        verified_capabilities = {}

        for capability_name, capability_values in capabilities.items():
            try:
                verified_values = await self._verify_capability_values(
                    resource_type, capability_name, capability_values
                )
                verified_capabilities[capability_name] = verified_values
                logger.debug(f"Verified {capability_name} for {resource_type}")
            except Exception as e:
                logger.warning(f"Failed to verify {capability_name} for {resource_type}: {e}")
                # Include original values with warning
                verified_capabilities[capability_name] = capability_values
                verified_capabilities[f"{capability_name}_verification_warning"] = str(e)

        return verified_capabilities

    async def verify_single_capability(self, resource_type: str, capability: str) -> bool:
        """Verify a single capability works with the API.

        Args:
            resource_type: Type of resource
            capability: Specific capability to verify

        Returns:
            True if capability is verified, False otherwise
        """
        try:
            # Get verification strategy for this capability type
            strategy = self._get_verification_strategy(capability)
            if not strategy:
                logger.warning(f"No verification strategy for capability: {capability}")
                return False

            # Perform verification
            result = await strategy(resource_type, capability)
            logger.debug(f"Verification result for {capability}: {result}")
            return result
        except Exception as e:
            logger.error(f"Error verifying capability {capability}: {e}")
            return False

    async def _verify_capability_values(
        self, resource_type: str, capability_name: str, values: Any
    ) -> Any:
        """Verify specific capability values.

        Args:
            resource_type: Type of resource
            capability_name: Name of the capability
            values: Values to verify

        Returns:
            Verified values
        """
        # Get verification strategy
        strategy = self._get_verification_strategy(capability_name)
        if not strategy:
            logger.debug(
                f"No verification strategy for {capability_name}, returning original values"
            )
            return values

        # Handle different value types
        if isinstance(values, list):
            verified_values = []
            for value in values:
                try:
                    if await strategy(resource_type, value):
                        verified_values.append(value)
                    else:
                        logger.warning(f"Failed to verify {capability_name} value: {value}")
                except Exception as e:
                    logger.warning(f"Error verifying {capability_name} value {value}: {e}")
            return verified_values
        elif isinstance(values, dict):
            # For schema-like structures, verify recursively
            return await self._verify_schema_values(resource_type, capability_name, values)
        else:
            # Single value verification
            if await strategy(resource_type, values):
                return values
            else:
                logger.warning(f"Failed to verify {capability_name} value: {values}")
                return None

    async def _verify_schema_values(
        self, resource_type: str, capability_name: str, schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Verify schema-like capability values.

        Args:
            resource_type: Type of resource
            capability_name: Name of the capability
            schema: Schema to verify

        Returns:
            Verified schema
        """
        # For now, return schema as-is since schema verification is complex
        # TODO: Implement schema field verification in future iterations
        return schema

    def _get_verification_strategy(self, capability_name: str) -> Optional[Callable]:
        """Get verification strategy for a capability.

        Args:
            capability_name: Name of the capability

        Returns:
            Verification strategy function or None
        """
        return self.verification_strategies.get(capability_name)

    # Verification strategy implementations

    async def _verify_currency_capability(self, resource_type: str, currency: str) -> bool:
        """Verify currency capability with enhanced API schema discovery."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for currency {currency}")
                # Try to get historical data from L3 cache
                cached_currencies = self._get_cached_capabilities("currencies", resource_type)
                if cached_currencies:
                    return currency in cached_currencies
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Currency verification unavailable - circuit breaker open and no cached data for {currency}"
                )

            # Try to get from cache first (L1/L2)
            cached_currencies = self._get_cached_capabilities("currencies", resource_type)
            if cached_currencies:
                logger.debug(
                    f"Using cached currencies for verification: {len(cached_currencies)} currencies"
                )
                return currency in cached_currencies

            # Discover currencies from API
            logger.info(f"Discovering currencies from API for {resource_type}")
            discovered_currencies = await self._discover_capabilities_from_api(
                capability_type="currencies",
                endpoint="products",
                field_path="plan.currency",
                resource_type=resource_type,
            )

            # If discovery successful, use discovered values
            if discovered_currencies:
                result = currency in discovered_currencies
                logger.debug(
                    f"Currency {currency} verification result from API discovery: {result}"
                )
                return result

            # If no currencies discovered, try alternative discovery method
            logger.info("Primary currency discovery failed, trying alternative method")
            alternative_currencies = await self._discover_currencies_alternative()
            if alternative_currencies:
                self._cache_capabilities("currencies", alternative_currencies, resource_type)
                result = currency in alternative_currencies
                logger.debug(
                    f"Currency {currency} verification result from alternative discovery: {result}"
                )
                return result

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All currency discovery methods failed for {currency}")
            raise ValueError(
                f"Currency verification failed - no API discovery methods successful for {currency}"
            )

        except Exception as e:
            logger.error(f"Currency verification failed for {currency}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Currency verification failed for {currency}: {str(e)}")

    async def _discover_currencies_alternative(self) -> Set[str]:
        """Alternative method to discover supported currencies."""
        try:
            # Try to discover from subscription data
            response = await self.client.get("subscriptions", params={"page": 0, "size": 20})
            self._record_api_success()

            currencies = set()
            if "data" in response and isinstance(response["data"], list):
                for subscription in response["data"]:
                    if "currency" in subscription:
                        currencies.add(subscription["currency"])
                    # Also check nested plan data
                    if "plan" in subscription and isinstance(subscription["plan"], dict):
                        if "currency" in subscription["plan"]:
                            currencies.add(subscription["plan"]["currency"])

            if currencies:
                logger.info(
                    f"Discovered {len(currencies)} currencies from subscriptions: {currencies}"
                )
                return currencies

            # If no currencies found in API data, raise error instead of hardcoded fallback
            raise ValueError("No currencies discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative currency discovery failed: {e}")
            raise ValueError(f"Failed to discover currencies from API: {str(e)}")

    async def _verify_plan_type_capability(self, resource_type: str, plan_type: str) -> bool:
        """Verify plan type capability with enhanced API schema discovery."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for plan type {plan_type}")
                # Try to get historical data from L3 cache
                cached_plan_types = self._get_cached_capabilities("plan_types", resource_type)
                if cached_plan_types:
                    return plan_type in cached_plan_types
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Plan type verification unavailable - circuit breaker open and no cached data for {plan_type}"
                )

            # Try to get from cache first (L1/L2)
            cached_plan_types = self._get_cached_capabilities("plan_types", resource_type)
            if cached_plan_types:
                logger.debug(
                    f"Using cached plan types for verification: {len(cached_plan_types)} types"
                )
                return plan_type in cached_plan_types

            # Discover plan types from API
            logger.info(f"Discovering plan types from API for {resource_type}")
            discovered_plan_types = await self._discover_capabilities_from_api(
                capability_type="plan_types",
                endpoint="products",
                field_path="plan.type",
                resource_type=resource_type,
            )

            # If discovery successful, use discovered values
            if discovered_plan_types:
                result = plan_type in discovered_plan_types
                logger.debug(
                    f"Plan type {plan_type} verification result from API discovery: {result}"
                )
                return result

            # If no plan types discovered, try alternative discovery method
            logger.info("Primary plan type discovery failed, trying alternative method")
            alternative_plan_types = await self._discover_plan_types_alternative()
            if alternative_plan_types:
                self._cache_capabilities("plan_types", alternative_plan_types, resource_type)
                result = plan_type in alternative_plan_types
                logger.debug(
                    f"Plan type {plan_type} verification result from alternative discovery: {result}"
                )
                return result

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All plan type discovery methods failed for {plan_type}")
            raise ValueError(
                f"Plan type verification failed - no API discovery methods successful for {plan_type}"
            )

        except Exception as e:
            logger.error(f"Plan type verification failed for {plan_type}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Plan type verification failed for {plan_type}: {str(e)}")

    async def _discover_plan_types_alternative(self) -> Set[str]:
        """Alternative method to discover supported plan types."""
        try:
            # Try to discover from subscription data
            response = await self.client.get("subscriptions", params={"page": 0, "size": 20})
            self._record_api_success()

            plan_types = set()
            if "data" in response and isinstance(response["data"], list):
                for subscription in response["data"]:
                    if "type" in subscription:
                        plan_types.add(subscription["type"])
                    # Also check nested plan data
                    if "plan" in subscription and isinstance(subscription["plan"], dict):
                        if "type" in subscription["plan"]:
                            plan_types.add(subscription["plan"]["type"])

            if plan_types:
                logger.info(
                    f"Discovered {len(plan_types)} plan types from subscriptions: {plan_types}"
                )
                return plan_types

            # If no plan types found in API data, raise error instead of hardcoded fallback
            raise ValueError("No plan types discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative plan type discovery failed: {e}")
            raise ValueError(f"Failed to discover plan types from API: {str(e)}")

    async def _verify_billing_period_capability(self, resource_type: str, period: str) -> bool:
        """Verify billing period capability with enhanced API schema discovery."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for billing period {period}")
                cached_periods = self._get_cached_capabilities("billing_periods", resource_type)
                if cached_periods:
                    return period in cached_periods
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Billing period verification unavailable - circuit breaker open and no cached data for {period}"
                )

            # Try to get from cache first (L1/L2)
            cached_periods = self._get_cached_capabilities("billing_periods", resource_type)
            if cached_periods:
                logger.debug(f"Using cached billing periods: {len(cached_periods)} periods")
                return period in cached_periods

            # Discover billing periods from API
            logger.info(f"Discovering billing periods from API for {resource_type}")
            discovered_periods = await self._discover_capabilities_from_api(
                capability_type="billing_periods",
                endpoint="products",
                field_path="plan.billingPeriod",
                resource_type=resource_type,
            )

            if discovered_periods:
                result = period in discovered_periods
                logger.debug(f"Billing period {period} verification from API discovery: {result}")
                return result

            # Alternative discovery from subscriptions
            alternative_periods = await self._discover_billing_periods_alternative()
            if alternative_periods:
                self._cache_capabilities("billing_periods", alternative_periods, resource_type)
                return period in alternative_periods

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All billing period discovery methods failed for {period}")
            raise ValueError(
                f"Billing period verification failed - no API discovery methods successful for {period}"
            )

        except Exception as e:
            logger.error(f"Billing period verification failed for {period}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Billing period verification failed for {period}: {str(e)}")

    async def _discover_billing_periods_alternative(self) -> Set[str]:
        """Alternative method to discover supported billing periods."""
        try:
            response = await self.client.get("subscriptions", params={"page": 0, "size": 20})
            self._record_api_success()

            periods = set()
            if "data" in response and isinstance(response["data"], list):
                for subscription in response["data"]:
                    if "billingPeriod" in subscription:
                        periods.add(subscription["billingPeriod"])
                    if "plan" in subscription and isinstance(subscription["plan"], dict):
                        if "billingPeriod" in subscription["plan"]:
                            periods.add(subscription["plan"]["billingPeriod"])

            if periods:
                logger.info(f"Discovered {len(periods)} billing periods: {periods}")
                return periods

            # If no periods found in API data, raise error instead of hardcoded fallback
            raise ValueError("No billing periods discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative billing period discovery failed: {e}")
            raise ValueError(f"Failed to discover billing periods from API: {str(e)}")

    async def _verify_trial_period_capability(self, resource_type: str, period: str) -> bool:
        """Verify trial period capability with API-only approach."""
        try:
            # Check circuit breaker
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for trial period {period}")
                cached_periods = self._get_cached_capabilities("trial_periods", resource_type)
                if cached_periods:
                    return period in cached_periods
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Trial period verification unavailable - circuit breaker open and no cached data for {period}"
                )

            # Try to get from cache first (L1/L2)
            cached_periods = self._get_cached_capabilities("trial_periods", resource_type)
            if cached_periods:
                logger.debug(f"Using cached trial periods: {len(cached_periods)} periods")
                return period in cached_periods

            # Discover trial periods from API
            logger.info(f"Discovering trial periods from API for {resource_type}")
            discovered_periods = await self._discover_capabilities_from_api(
                capability_type="trial_periods",
                endpoint="products",
                field_path="plan.trialPeriod",
                resource_type=resource_type,
            )

            if discovered_periods:
                result = period in discovered_periods
                logger.debug(f"Trial period {period} verification from API discovery: {result}")
                return result

            # Alternative discovery from subscriptions
            alternative_periods = await self._discover_trial_periods_alternative()
            if alternative_periods:
                self._cache_capabilities("trial_periods", alternative_periods, resource_type)
                return period in alternative_periods

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All trial period discovery methods failed for {period}")
            raise ValueError(
                f"Trial period verification failed - no API discovery methods successful for {period}"
            )

        except Exception as e:
            logger.error(f"Trial period verification failed for {period}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Trial period verification failed for {period}: {str(e)}")

    async def _discover_trial_periods_alternative(self) -> Set[str]:
        """Alternative method to discover supported trial periods."""
        try:
            response = await self.client.get("subscriptions", params={"page": 0, "size": 20})
            self._record_api_success()

            periods = set()
            if "data" in response and isinstance(response["data"], list):
                for subscription in response["data"]:
                    if "trialPeriod" in subscription:
                        periods.add(subscription["trialPeriod"])
                    if "plan" in subscription and isinstance(subscription["plan"], dict):
                        if "trialPeriod" in subscription["plan"]:
                            periods.add(subscription["plan"]["trialPeriod"])

            if periods:
                logger.info(f"Discovered {len(periods)} trial periods: {periods}")
                return periods

            # If no periods found in API data, raise error instead of hardcoded fallback
            raise ValueError("No trial periods discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative trial period discovery failed: {e}")
            raise ValueError(f"Failed to discover trial periods from API: {str(e)}")

    async def _verify_user_role_capability(self, resource_type: str, role: str) -> bool:
        """Verify user role capability with API-only approach."""
        try:
            # Check circuit breaker
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for user role {role}")
                cached_roles = self._get_cached_capabilities("user_roles", resource_type)
                if cached_roles:
                    return role in cached_roles
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"User role verification unavailable - circuit breaker open and no cached data for {role}"
                )

            # Try to get from cache first (L1/L2)
            cached_roles = self._get_cached_capabilities("user_roles", resource_type)
            if cached_roles:
                logger.debug(f"Using cached user roles: {len(cached_roles)} roles")
                return role in cached_roles

            # Discover user roles from API
            logger.info(f"Discovering user roles from API for {resource_type}")
            discovered_roles = await self._discover_capabilities_from_api(
                capability_type="user_roles",
                endpoint="users",
                field_path="role",
                resource_type=resource_type,
            )

            if discovered_roles:
                result = role in discovered_roles
                logger.debug(f"User role {role} verification from API discovery: {result}")
                return result

            # Alternative discovery method
            alternative_roles = await self._discover_user_roles_alternative()
            if alternative_roles:
                self._cache_capabilities("user_roles", alternative_roles, resource_type)
                return role in alternative_roles

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All user role discovery methods failed for {role}")
            raise ValueError(
                f"User role verification failed - no API discovery methods successful for {role}"
            )

        except Exception as e:
            logger.error(f"User role verification failed for {role}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"User role verification failed for {role}: {str(e)}")

    async def _discover_user_roles_alternative(self) -> Set[str]:
        """Alternative method to discover supported user roles."""
        try:
            response = await self.client.get("organizations", params={"page": 0, "size": 20})
            self._record_api_success()

            roles = set()
            if "data" in response and isinstance(response["data"], list):
                for org in response["data"]:
                    # Check for user roles in organization data
                    if "users" in org and isinstance(org["users"], list):
                        for user in org["users"]:
                            if "role" in user:
                                roles.add(user["role"])
                            if "roles" in user and isinstance(user["roles"], list):
                                roles.update(user["roles"])

            if roles:
                logger.info(f"Discovered {len(roles)} user roles: {roles}")
                return roles

            # If no roles found in API data, raise error instead of hardcoded fallback
            raise ValueError("No user roles discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative user role discovery failed: {e}")
            raise ValueError(f"Failed to discover user roles from API: {str(e)}")

    async def _verify_organization_type_capability(self, resource_type: str, org_type: str) -> bool:
        """Verify organization type capability with API-only approach."""
        try:
            # Check circuit breaker
            if self._is_circuit_open():
                logger.debug(
                    f"Circuit breaker open, using cached data for organization type {org_type}"
                )
                cached_org_types = self._get_cached_capabilities(
                    "organization_types", resource_type
                )
                if cached_org_types:
                    return org_type in cached_org_types
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Organization type verification unavailable - circuit breaker open and no cached data for {org_type}"
                )

            # Try to get from cache first (L1/L2)
            cached_org_types = self._get_cached_capabilities("organization_types", resource_type)
            if cached_org_types:
                logger.debug(f"Using cached organization types: {len(cached_org_types)} types")
                return org_type in cached_org_types

            # Discover organization types from API
            logger.info(f"Discovering organization types from API for {resource_type}")
            discovered_org_types = await self._discover_capabilities_from_api(
                capability_type="organization_types",
                endpoint="organizations",
                field_path="type",
                resource_type=resource_type,
            )

            if discovered_org_types:
                result = org_type in discovered_org_types
                logger.debug(
                    f"Organization type {org_type} verification from API discovery: {result}"
                )
                return result

            # Alternative discovery method
            alternative_org_types = await self._discover_organization_types_alternative()
            if alternative_org_types:
                self._cache_capabilities("organization_types", alternative_org_types, resource_type)
                return org_type in alternative_org_types

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All organization type discovery methods failed for {org_type}")
            raise ValueError(
                f"Organization type verification failed - no API discovery methods successful for {org_type}"
            )

        except Exception as e:
            logger.error(f"Organization type verification failed for {org_type}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Organization type verification failed for {org_type}: {str(e)}")

    async def _discover_organization_types_alternative(self) -> Set[str]:
        """Alternative method to discover supported organization types."""
        try:
            response = await self.client.get("organizations", params={"page": 0, "size": 20})
            self._record_api_success()

            org_types = set()
            if "data" in response and isinstance(response["data"], list):
                for org in response["data"]:
                    if "type" in org:
                        org_types.add(org["type"])
                    if "organizationType" in org:
                        org_types.add(org["organizationType"])

            if org_types:
                logger.info(f"Discovered {len(org_types)} organization types: {org_types}")
                return org_types

            # If no types found in API data, raise error instead of hardcoded fallback
            raise ValueError("No organization types discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative organization type discovery failed: {e}")
            raise ValueError(f"Failed to discover organization types from API: {str(e)}")

    async def _verify_alert_type_capability(self, resource_type: str, alert_type: str) -> bool:
        """Verify alert type capability with API-only approach."""
        try:
            # Check circuit breaker
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for alert type {alert_type}")
                cached_alert_types = self._get_cached_capabilities("alert_types", resource_type)
                if cached_alert_types:
                    return alert_type in cached_alert_types
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Alert type verification unavailable - circuit breaker open and no cached data for {alert_type}"
                )

            # Try to get from cache first (L1/L2)
            cached_alert_types = self._get_cached_capabilities("alert_types", resource_type)
            if cached_alert_types:
                logger.debug(f"Using cached alert types: {len(cached_alert_types)} types")
                return alert_type in cached_alert_types

            # Use the discovery service to get alert types
            logger.info(f"Discovering alert types from API for {resource_type}")
            from ..capability_manager.discovery import CapabilityDiscovery

            discovery = CapabilityDiscovery(self.client)

            # Get alert types from the alert capabilities
            alert_capabilities = await discovery._discover_alert_capabilities()
            discovered_alert_types = set(alert_capabilities.get("alert_types", []))

            if discovered_alert_types:
                self._cache_capabilities("alert_types", discovered_alert_types, resource_type)
                result = alert_type in discovered_alert_types
                logger.debug(
                    f"Alert type {alert_type} verification from discovery service: {result}"
                )
                return result

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All alert type discovery methods failed for {alert_type}")
            raise ValueError(
                f"Alert type verification failed - no API discovery methods successful for {alert_type}"
            )

        except Exception as e:
            logger.error(f"Alert type verification failed for {alert_type}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Alert type verification failed for {alert_type}: {str(e)}")

    async def _verify_metric_capability(self, resource_type: str, metric: str) -> bool:
        """Verify metric capability with proper resource type routing."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for metric {metric}")
                cached_metrics = self._get_cached_capabilities("metrics", resource_type)
                if cached_metrics:
                    return metric in cached_metrics
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Metric verification unavailable - circuit breaker open and no cached data for {metric}"
                )

            # Try to get from cache first (L1/L2)
            cached_metrics = self._get_cached_capabilities("metrics", resource_type)
            if cached_metrics:
                logger.debug(f"Using cached metrics: {len(cached_metrics)} metrics")
                return metric in cached_metrics

            # Route to appropriate discovery based on resource type
            logger.info(f"Discovering metrics from API for {resource_type}")
            from ..capability_manager.discovery import CapabilityDiscovery

            discovery = CapabilityDiscovery(self.client)

            discovered_metrics = set()

            if resource_type == "alerts":
                # For alerts: Get alert/monitoring metrics (TOTAL_COST, ERROR_RATE, etc.)
                alert_capabilities = await discovery._discover_alert_capabilities()
                metrics_dict = alert_capabilities.get("metrics", {})
                if isinstance(metrics_dict, dict):
                    # Extract all metrics from nested categories
                    for metric_category in metrics_dict.values():
                        if isinstance(metric_category, list):
                            discovered_metrics.update(metric_category)
                elif isinstance(metrics_dict, list):
                    discovered_metrics.update(metrics_dict)
                logger.debug(f"Alert metrics discovered: {discovered_metrics}")

            elif resource_type == "metering":
                # For metering: This is NOT about traditional metrics
                # It's about AI transaction field validation (model, provider, etc.)
                # The "metric" parameter here should be a transaction field name
                metering_capabilities = await discovery._discover_metering_capabilities()
                transaction_fields = metering_capabilities.get("transaction_fields", {})

                # Check if the "metric" is actually a valid transaction field
                required_fields = set(transaction_fields.get("required", []))
                optional_fields = set(transaction_fields.get("optional", []))
                discovered_metrics = required_fields.union(optional_fields)
                logger.debug(f"Metering transaction fields discovered: {discovered_metrics}")

            else:
                # For other resource types, raise error to force proper API integration
                logger.error(f"Unknown resource type for metric verification: {resource_type}")
                raise ValueError(
                    f"Metric verification not supported for resource type: {resource_type}"
                )

            if discovered_metrics:
                self._cache_capabilities("metrics", discovered_metrics, resource_type)
                result = metric in discovered_metrics
                logger.debug(f"Metric '{metric}' verification for {resource_type}: {result}")
                return result

            # If no metrics discovered, raise error to force proper API integration
            logger.error(f"No metrics discovered for {resource_type}")
            raise ValueError(
                f"Metric verification failed - no API discovery methods successful for {metric}"
            )

        except Exception as e:
            logger.error(f"Metric verification failed for {metric} on {resource_type}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Metric verification failed for {metric}: {str(e)}")

    async def _verify_operator_capability(self, resource_type: str, operator: str) -> bool:
        """Verify operator capability with enhanced API schema discovery."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for operator {operator}")
                cached_operators = self._get_cached_capabilities("operators", resource_type)
                if cached_operators:
                    return operator in cached_operators
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Operator verification unavailable - circuit breaker open and no cached data for {operator}"
                )

            # Try to get from cache first (L1/L2)
            cached_operators = self._get_cached_capabilities("operators", resource_type)
            if cached_operators:
                logger.debug(f"Using cached operators: {len(cached_operators)} operators")
                return operator in cached_operators

            # Use the discovery service to get operators
            logger.info(f"Discovering operators from API for {resource_type}")
            from ..capability_manager.discovery import CapabilityDiscovery

            discovery = CapabilityDiscovery(self.client)

            # Get operators from the metering capabilities
            metering_capabilities = await discovery._discover_metering_capabilities()
            discovered_operators = set(metering_capabilities.get("operators", []))

            if discovered_operators:
                self._cache_capabilities("operators", discovered_operators, resource_type)
                result = operator in discovered_operators
                logger.debug(f"Operator {operator} verification from discovery service: {result}")
                return result

            # If no operators discovered, raise error to force proper API integration
            logger.error(f"No operators discovered for {resource_type}")
            raise ValueError(
                f"Operator verification failed - no API discovery methods successful for {operator}"
            )

        except Exception as e:
            logger.error(f"Operator verification failed for {operator}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Operator verification failed for {operator}: {str(e)}")

    async def _verify_source_type_capability(self, resource_type: str, source_type: str) -> bool:
        """Verify source type capability with enhanced API schema discovery."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(
                    f"Circuit breaker open, using cached data for source type {source_type}"
                )
                cached_source_types = self._get_cached_capabilities("source_types", resource_type)
                if cached_source_types:
                    return source_type in cached_source_types
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Source type verification unavailable - circuit breaker open and no cached data for {source_type}"
                )

            # Try to get from cache first (L1/L2)
            cached_source_types = self._get_cached_capabilities("source_types", resource_type)
            if cached_source_types:
                logger.debug(f"Using cached source types: {len(cached_source_types)} types")
                return source_type in cached_source_types

            # Discover source types from API
            logger.info(f"Discovering source types from API for {resource_type}")
            discovered_source_types = await self._discover_capabilities_from_api(
                capability_type="source_types",
                endpoint="sources",
                field_path="type",
                resource_type=resource_type,
            )

            if discovered_source_types:
                result = source_type in discovered_source_types
                logger.debug(f"Source type {source_type} verification from API discovery: {result}")
                return result

            # Alternative discovery method
            alternative_source_types = await self._discover_source_types_alternative()
            if alternative_source_types:
                self._cache_capabilities("source_types", alternative_source_types, resource_type)
                return source_type in alternative_source_types

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All source type discovery methods failed for {source_type}")
            raise ValueError(
                f"Source type verification failed - no API discovery methods successful for {source_type}"
            )

        except Exception as e:
            logger.error(f"Source type verification failed for {source_type}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Source type verification failed for {source_type}: {str(e)}")

    async def _discover_source_types_alternative(self) -> Set[str]:
        """Alternative method to discover supported source types."""
        try:
            response = await self.client.get("sources", params={"page": 0, "size": 20})
            self._record_api_success()

            source_types = set()
            if "data" in response and isinstance(response["data"], list):
                for source in response["data"]:
                    if "type" in source:
                        source_types.add(source["type"])
                    if "sourceType" in source:
                        source_types.add(source["sourceType"])

            if source_types:
                logger.info(f"Discovered {len(source_types)} source types: {source_types}")
                return source_types

            # If no source types found in API data, raise error instead of hardcoded fallback
            raise ValueError("No source types discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative source type discovery failed: {e}")
            raise ValueError(f"Failed to discover source types from API: {str(e)}")

    async def _verify_element_type_capability(self, resource_type: str, element_type: str) -> bool:
        """Verify metering element type capability with enhanced API schema discovery."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(
                    f"Circuit breaker open, using cached data for element type {element_type}"
                )
                cached_element_types = self._get_cached_capabilities("element_types", resource_type)
                if cached_element_types:
                    return element_type in cached_element_types
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Element type verification unavailable - circuit breaker open and no cached data for {element_type}"
                )

            # Try to get from cache first (L1/L2)
            cached_element_types = self._get_cached_capabilities("element_types", resource_type)
            if cached_element_types:
                logger.debug(f"Using cached element types: {len(cached_element_types)} types")
                return element_type in cached_element_types

            # Discover element types from API
            logger.info(f"Discovering element types from API for {resource_type}")
            discovered_element_types = await self._discover_capabilities_from_api(
                capability_type="element_types",
                endpoint="metering-elements",
                field_path="type",
                resource_type=resource_type,
            )

            if discovered_element_types:
                result = element_type in discovered_element_types
                logger.debug(
                    f"Element type {element_type} verification from API discovery: {result}"
                )
                return result

            # Alternative discovery method
            alternative_element_types = await self._discover_element_types_alternative()
            if alternative_element_types:
                self._cache_capabilities("element_types", alternative_element_types, resource_type)
                return element_type in alternative_element_types

            # If all discovery methods fail, raise error to force proper API integration
            logger.error(f"All element type discovery methods failed for {element_type}")
            raise ValueError(
                f"Element type verification failed - no API discovery methods successful for {element_type}"
            )

        except Exception as e:
            logger.error(f"Element type verification failed for {element_type}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Element type verification failed for {element_type}: {str(e)}")

    async def _discover_element_types_alternative(self) -> Set[str]:
        """Alternative method to discover supported element types."""
        try:
            response = await self.client.get("metering-elements", params={"page": 0, "size": 20})
            self._record_api_success()

            element_types = set()
            if "data" in response and isinstance(response["data"], list):
                for element in response["data"]:
                    if "type" in element:
                        element_types.add(element["type"])
                    if "dataType" in element:
                        element_types.add(element["dataType"])

            if element_types:
                logger.info(f"Discovered {len(element_types)} element types: {element_types}")
                return element_types

            # If no element types found in API data, raise error instead of hardcoded fallback
            raise ValueError("No element types discovered from API - UCM integration required")

        except Exception as e:
            self._record_api_failure()
            logger.warning(f"Alternative element type discovery failed: {e}")
            raise ValueError(f"Failed to discover element types from API: {str(e)}")

    async def _verify_provider_capability(self, resource_type: str, provider: str) -> bool:
        """Verify AI provider capability by calling AI models endpoint directly."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for provider {provider}")
                cached_providers = self._get_cached_capabilities("providers", resource_type)
                if cached_providers:
                    return provider in cached_providers
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Provider verification unavailable - circuit breaker open and no cached data for {provider}"
                )

            # Try to get from cache first (L1/L2)
            cached_providers = self._get_cached_capabilities("providers", resource_type)
            if cached_providers:
                logger.debug(f"Using cached providers: {len(cached_providers)} providers")
                return provider in cached_providers

            # Call AI models endpoint directly to get ALL providers
            logger.info(f"Verifying provider {provider} by calling AI models endpoint")

            try:
                # Use the existing working AI models client method
                models_response = await self.client.get_ai_models(page=0, size=1000)
                self._record_api_success()

                discovered_providers = set()

                if (
                    "_embedded" in models_response
                    and "aIModelResourceList" in models_response["_embedded"]
                ):
                    models = models_response["_embedded"]["aIModelResourceList"]

                    for model in models:
                        model_provider = model.get("provider", "")
                        if model_provider:
                            discovered_providers.add(model_provider)

                logger.info(
                    f"Discovered {len(discovered_providers)} providers from AI models endpoint: {sorted(list(discovered_providers))}"
                )

                if discovered_providers:
                    self._cache_capabilities("providers", discovered_providers, resource_type)
                    result = provider in discovered_providers
                    logger.debug(
                        f"Provider {provider} verification from AI models endpoint: {result}"
                    )
                    return result

            except Exception as api_error:
                self._record_api_failure()
                logger.warning(
                    f"AI models endpoint call failed for provider verification: {api_error}"
                )
                # No conservative fallback - raise error to force proper API integration
                raise ValueError(
                    f"Provider verification failed - AI models endpoint unavailable: {str(api_error)}"
                )

            # If no providers discovered, raise error to force proper API integration
            logger.error(f"No providers discovered for {provider}")
            raise ValueError(
                f"Provider verification failed - no API discovery methods successful for {provider}"
            )

        except Exception as e:
            logger.error(f"Provider verification failed for {provider}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Provider verification failed for {provider}: {str(e)}")

    async def _verify_model_capability(self, resource_type: str, model: str) -> bool:
        """Verify AI model capability by calling AI models endpoint directly."""
        try:
            # Check circuit breaker first
            if self._is_circuit_open():
                logger.debug(f"Circuit breaker open, using cached data for model {model}")
                cached_models = self._get_cached_capabilities("models", resource_type)
                if cached_models:
                    return model in cached_models
                # No hardcoded fallback - raise error to force proper API integration
                raise ValueError(
                    f"Model verification unavailable - circuit breaker open and no cached data for {model}"
                )

            # Try to get from cache first (L1/L2)
            cached_models = self._get_cached_capabilities("models", resource_type)
            if cached_models:
                logger.debug(f"Using cached models: {len(cached_models)} models")
                return model in cached_models

            # Call AI models endpoint directly to get ALL models
            logger.info(f"Verifying model {model} by calling AI models endpoint")

            try:
                # Use the existing working AI models client method
                models_response = await self.client.get_ai_models(page=0, size=1000)
                self._record_api_success()

                discovered_models = set()

                if (
                    "_embedded" in models_response
                    and "aIModelResourceList" in models_response["_embedded"]
                ):
                    models = models_response["_embedded"]["aIModelResourceList"]

                    for model_entry in models:
                        model_name = model_entry.get("name", "")
                        if model_name:
                            discovered_models.add(model_name)

                logger.info(f"Discovered {len(discovered_models)} models from AI models endpoint")

                if discovered_models:
                    self._cache_capabilities("models", discovered_models, resource_type)
                    result = model in discovered_models
                    logger.debug(f"Model {model} verification from AI models endpoint: {result}")
                    return result

            except Exception as api_error:
                self._record_api_failure()
                logger.warning(
                    f"AI models endpoint call failed for model verification: {api_error}"
                )
                # No conservative fallback - raise error to force proper API integration
                raise ValueError(
                    f"Model verification failed - AI models endpoint unavailable: {str(api_error)}"
                )

            # If no models discovered, raise error to force proper API integration
            logger.error(f"No models discovered for {model}")
            raise ValueError(
                f"Model verification failed - no API discovery methods successful for {model}"
            )

        except Exception as e:
            logger.error(f"Model verification failed for {model}: {e}")
            # No hardcoded fallback - re-raise to force proper error handling
            raise ValueError(f"Model verification failed for {model}: {str(e)}")
