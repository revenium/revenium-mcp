"""AI Client for query routing with rate limiting and caching.

This module provides the AI client interface for the Universal Query Interpreter,
including rate limiting, caching, circuit breaker pattern, and cost tracking.
"""

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

# Load environment variables BEFORE importing middleware
from dotenv import load_dotenv

load_dotenv()

import httpx
import openai

# revenium middleware is critical to this project, do not edit the configuration, remove it,
# or assume it is set up incorrectly.  It is a working implementation, you must ask for
# permission before changing any Revenium-related code.
import revenium_middleware_openai  # Import to enable middleware for tracking spending
from loguru import logger

from ..core.redis_like_cache import RedisLikeCache
from .metadata_builder import ReveniumMetadataBuilder
from .models import AIClientConfig, RoutingMethod, RoutingResult, RoutingStatus


class AIClientError(Exception):
    """Base exception for AI client errors."""

    pass


class RateLimitExceededError(AIClientError):
    """Raised when rate limit is exceeded."""

    pass


class CircuitBreakerOpenError(AIClientError):
    """Raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """Simple circuit breaker implementation for AI service reliability."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half_open

    def is_healthy(self) -> bool:
        """Check if circuit breaker allows requests."""
        if self.state == "closed":
            return True

        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half_open"
                return True
            return False

        # half_open state
        return True

    def record_success(self) -> None:
        """Record successful operation."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


class RateLimiter:
    """Token bucket rate limiter for AI requests."""

    def __init__(self, requests_per_minute: int):
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute
        """
        self.requests_per_minute = requests_per_minute
        self.tokens = requests_per_minute
        self.last_refill = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self) -> bool:
        """Acquire a token for making a request.

        Returns:
            True if token acquired, False if rate limited
        """
        async with self.lock:
            now = time.time()
            time_passed = now - self.last_refill

            # Refill tokens based on time passed
            tokens_to_add = time_passed * (self.requests_per_minute / 60.0)
            self.tokens = min(self.requests_per_minute, self.tokens + tokens_to_add)
            self.last_refill = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True

            return False


class AIClient:
    """AI client for query routing with enterprise-grade reliability features."""

    def __init__(self, config: Optional[AIClientConfig] = None):
        """Initialize AI client.

        Args:
            config: AI client configuration
        """
        self.config = config or self._load_default_config()
        self.circuit_breaker = CircuitBreaker()
        self.rate_limiter = RateLimiter(self.config.rate_limit_requests_per_minute)
        self.cache = RedisLikeCache() if self.config.enable_caching else None
        self.cost_tracker = {"total_requests": 0, "total_tokens": 0}
        self.metadata_builder = ReveniumMetadataBuilder()

        # Fallback configuration
        self.enable_fallback = os.getenv("REVENIUM_ENABLE_FALLBACK", "true").lower() == "true"
        self.fallback_on_middleware_error = (
            os.getenv("REVENIUM_FALLBACK_ON_ERROR", "true").lower() == "true"
        )

        # Fallback configuration
        self.enable_fallback = os.getenv("REVENIUM_ENABLE_FALLBACK", "true").lower() == "true"
        self.fallback_on_middleware_error = (
            os.getenv("REVENIUM_FALLBACK_ON_ERROR", "true").lower() == "true"
        )

        # Initialize OpenAI client with Revenium middleware
        # Note: Using synchronous client as per Revenium middleware documentation
        self.openai_client = openai.OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

        # Keep HTTP client for backward compatibility (if needed)
        self.http_client = httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers=(
                {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
            ),
        )

        logger.info(
            f"AI Client initialized with model: {self.config.model_name} (using OpenAI SDK with Revenium middleware)"
        )

    def _load_default_config(self) -> AIClientConfig:
        """Load default configuration from environment variables."""
        return AIClientConfig(
            model_name=os.getenv("AI_MODEL_NAME", "gpt-3.5-turbo"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
            max_tokens=int(
                os.getenv("AI_MAX_TOKENS", "1000")
            ),  # High limit for testing - tune later based on real usage
            temperature=float(os.getenv("AI_TEMPERATURE", "0.1")),
            timeout_seconds=int(os.getenv("AI_TIMEOUT_SECONDS", "30")),
            rate_limit_requests_per_minute=int(os.getenv("AI_RATE_LIMIT", "60")),
        )

    async def route_query(
        self, query: str, tool_context: str, available_tools: List[str]
    ) -> RoutingResult:
        """Route a natural language query to appropriate tool and action.

        Args:
            query: Natural language query to route
            tool_context: Context about the current tool domain
            available_tools: List of available tools for routing

        Returns:
            RoutingResult with tool selection and parameters

        Raises:
            AIClientError: If AI routing fails
        """
        start_time = time.time()

        try:
            # Check circuit breaker
            if not self.circuit_breaker.is_healthy():
                raise CircuitBreakerOpenError("AI service circuit breaker is open")

            # Check rate limiting
            if not await self.rate_limiter.acquire():
                raise RateLimitExceededError("AI service rate limit exceeded")

            # Check cache first
            cache_key = self._generate_cache_key(query, tool_context, available_tools)
            if self.cache:
                cached_result = await self.cache.get(cache_key)
                if cached_result:
                    logger.debug(f"Cache hit for query: {query[:50]}...")
                    return RoutingResult(**cached_result)

            # Make AI request
            result = await self._make_ai_request(query, tool_context, available_tools)

            # Cache successful result
            if self.cache and result.is_successful():
                await self.cache.set(cache_key, result.to_dict(), ttl=self.config.cache_ttl_seconds)

            # Record success
            self.circuit_breaker.record_success()
            result.response_time_ms = (time.time() - start_time) * 1000

            return result

        except Exception as e:
            # Record failure
            self.circuit_breaker.record_failure()

            logger.error(f"AI routing failed for query '{query[:50]}...': {e}")
            raise AIClientError(f"AI routing failed: {e}") from e

    async def _make_ai_request(
        self, query: str, tool_context: str, available_tools: List[str]
    ) -> RoutingResult:
        """Make the actual AI request for query routing using OpenAI SDK with Revenium middleware."""
        prompt = self._build_routing_prompt(query, tool_context, available_tools)

        # Build comprehensive metadata for Revenium tracking
        usage_metadata = self.metadata_builder.build_routing_metadata(
            query=query, tool_context=tool_context, available_tools=available_tools
        )

        try:
            # Use OpenAI SDK with Revenium middleware
            # Run synchronous OpenAI call in thread pool to maintain async interface
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.openai_client.chat.completions.create(
                    model=self.config.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                    response_format={"type": "json_object"},
                    usage_metadata=usage_metadata,
                ),
            )

            # Track usage (the middleware will also track this)
            self.cost_tracker["total_requests"] += 1
            if response.usage:
                self.cost_tracker["total_tokens"] += response.usage.total_tokens

            # Parse AI response
            ai_content = response.choices[0].message.content

            # Log the raw response for debugging
            logger.debug(f"Raw AI response: {ai_content}")

            if not ai_content:
                raise AIClientError("Empty response from AI model")

            try:
                routing_data = json.loads(ai_content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI response as JSON. Raw content: {ai_content}")
                raise AIClientError(f"Failed to parse AI response as JSON: {e}")

            return self._parse_ai_response(routing_data)

        except Exception as e:
            # Check if fallback is enabled and appropriate
            if self.enable_fallback and self.fallback_on_middleware_error:
                logger.warning(f"OpenAI SDK error during routing: {e}. Attempting fallback...")

                try:
                    # Fallback to direct HTTP request (without middleware)
                    return await self._fallback_ai_request(prompt, usage_metadata)
                except Exception as fallback_error:
                    logger.error(f"Both OpenAI SDK and fallback failed: {e}, {fallback_error}")
                    raise AIClientError(f"OpenAI API error during routing: {e}")
            else:
                # Fallback disabled, fail immediately
                logger.error(f"OpenAI SDK error during routing (fallback disabled): {e}")
                raise AIClientError(f"OpenAI API error during routing: {e}")

    async def _fallback_ai_request(
        self, prompt: str, usage_metadata: Dict[str, Any]
    ) -> RoutingResult:
        """Fallback AI request using direct HTTP (without middleware).

        This method provides a fallback when the OpenAI SDK with middleware fails,
        ensuring the MCP server continues to function even if Revenium tracking fails.
        """
        logger.info("Using fallback HTTP client for AI request (Revenium tracking disabled)")

        request_data = {
            "model": self.config.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "response_format": {"type": "json_object"},
        }

        try:
            response = await self.http_client.post(
                f"{self.config.base_url}/chat/completions", json=request_data
            )
            response.raise_for_status()

            response_data = response.json()

            # Track usage locally (since middleware is not working)
            self.cost_tracker["total_requests"] += 1
            if "usage" in response_data:
                self.cost_tracker["total_tokens"] += response_data["usage"].get("total_tokens", 0)

            # Parse AI response
            ai_content = response_data["choices"][0]["message"]["content"]

            if not ai_content:
                raise AIClientError("Empty response from AI model")

            try:
                routing_data = json.loads(ai_content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI response as JSON. Raw content: {ai_content}")
                raise AIClientError(f"Failed to parse AI response as JSON: {e}")

            return self._parse_ai_response(routing_data)

        except httpx.HTTPError as e:
            raise AIClientError(f"HTTP error during fallback AI request: {e}")
        except KeyError as e:
            raise AIClientError(f"Unexpected AI response format in fallback: {e}")

    def _build_routing_prompt(
        self, query: str, tool_context: str, available_tools: List[str]
    ) -> str:
        """Build the prompt for AI query routing with focus on 5 core operations."""
        return f"""You are a query router for a platform API. You must respond with valid JSON only.

Route this natural language query to the appropriate tool and action:

Query: "{query}"
Context: {tool_context}
Available Tools: {', '.join(available_tools)}

PRIORITY OPERATIONS (Phase 1 Focus):
1. CREATE PRODUCT: "create product", "add product", "new product" → products.create
2. LIST ALERTS: "list alerts", "show alerts", "get alerts" → alerts.list
3. SHOW SUBSCRIPTIONS: "show subscriptions", "list subscriptions", "get subscriptions" → subscriptions.list
4. ADD CUSTOMER: "add customer", "create customer", "new customer" → customers.create
5. START WORKFLOW: "start workflow", "begin workflow", "initiate workflow" → workflows.start

Tool-Action Mappings:
- products: create, list, get, update, delete
- alerts: list, get, create, update, delete
- subscriptions: list, get, create, update, delete
- customers: list, get, create, update, delete
- workflows: list, get, start, next_step, complete_step

Parameter Extraction:
- Extract names from: "called X", "named X", "product X"
- Extract IDs from: "id: X", "ID X", alphanumeric strings 8+ chars
- Extract emails from: standard email patterns
- Extract amounts from: "$X", "X dollars", numeric values
- Extract time periods from: "yesterday", "last week", "last month"

You must respond with valid JSON in this exact format:
{{
    "tool_name": "selected_tool_name",
    "action": "selected_action",
    "parameters": {{"param1": "value1", "param2": "value2"}},
    "confidence": 0.95,
    "reasoning": "Brief explanation"
}}

Confidence should be 0.0-1.0. Respond only with valid JSON, no other text."""

    def _parse_ai_response(self, routing_data: Dict[str, Any]) -> RoutingResult:
        """Parse AI response into RoutingResult."""
        from .parameter_extractor import ExtractedParameters

        parameters = ExtractedParameters(
            parameters=routing_data.get("parameters", {}),
            confidence=routing_data.get("confidence", 0.0),
            extraction_method="ai",
        )

        return RoutingResult(
            tool_name=routing_data.get("tool_name", ""),
            action=routing_data.get("action", ""),
            parameters=parameters,
            confidence=routing_data.get("confidence", 0.0),
            routing_method=RoutingMethod.AI,
            status=RoutingStatus.SUCCESS,
        )

    def _generate_cache_key(self, query: str, tool_context: str, available_tools: List[str]) -> str:
        """Generate cache key for the query."""
        import hashlib

        content = f"{query}|{tool_context}|{','.join(sorted(available_tools))}"
        return f"ai_routing:{hashlib.sha256(content.encode()).hexdigest()}"

    async def close(self) -> None:
        """Close the AI client and cleanup resources."""
        await self.http_client.aclose()
        # Synchronous OpenAI client doesn't need async close
        if hasattr(self.openai_client, "close"):
            self.openai_client.close()
        logger.info("AI Client closed")

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost tracking summary."""
        return self.cost_tracker.copy()
