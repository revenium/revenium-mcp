"""Metadata builder for Revenium AI usage tracking.

This module provides utilities for building comprehensive metadata for AI calls
that will be tracked by the Revenium middleware.
"""

import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class MCPMetadataConfig:
    """Configuration for MCP metadata generation."""

    product: str = "MCP"
    agent_type: str = "mcp-server"
    organization_id: str = "revenium-mcp-server"
    subscription_id: str = "mcp-ai-routing"
    enable_detailed_tracking: bool = True
    include_query_context: bool = True


class ReveniumMetadataBuilder:
    """Builder for creating Revenium usage metadata for AI calls."""

    def __init__(self, config: Optional[MCPMetadataConfig] = None):
        """Initialize metadata builder.

        Args:
            config: Configuration for metadata generation
        """
        self.config = config or self._load_default_config()
        logger.debug(f"Metadata builder initialized with config: {self.config}")

    def _load_default_config(self) -> MCPMetadataConfig:
        """Load default configuration from environment variables."""
        return MCPMetadataConfig(
            product=os.getenv("REVENIUM_MCP_PRODUCT", "MCP"),
            agent_type=os.getenv("REVENIUM_MCP_AGENT_TYPE", "mcp-server"),
            organization_id=os.getenv("REVENIUM_MCP_ORG_ID", "revenium-mcp-server"),
            subscription_id=os.getenv("REVENIUM_MCP_SUBSCRIPTION_ID", "mcp-ai-routing"),
            enable_detailed_tracking=os.getenv("REVENIUM_MCP_DETAILED_TRACKING", "true").lower()
            == "true",
            include_query_context=os.getenv("REVENIUM_MCP_INCLUDE_CONTEXT", "true").lower()
            == "true",
        )

    def build_routing_metadata(
        self,
        query: str,
        tool_context: str,
        available_tools: List[str],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build metadata for query routing operations.

        Args:
            query: The natural language query being routed
            tool_context: Context about the current tool domain
            available_tools: List of available tools for routing
            session_id: Optional session identifier

        Returns:
            Dictionary containing metadata for Revenium tracking
        """
        # Generate unique trace ID for this routing operation
        trace_id = session_id or f"mcp-routing-{uuid.uuid4().hex[:12]}"

        # Build base metadata
        metadata = {
            "product": self.config.product,
            "agent": self.config.agent_type,
            "trace_id": trace_id,
            "task_type": f"query-routing-{tool_context}",
            "organization_id": self.config.organization_id,
            "subscription_id": self.config.subscription_id,
        }

        # Add detailed tracking if enabled
        if self.config.enable_detailed_tracking:
            metadata.update(
                {
                    "task_id": f"route-{uuid.uuid4().hex[:8]}",
                    "response_quality_score": 0.9,  # Default high quality for routing
                    "is_streamed": False,
                }
            )

        # Add query context if enabled
        if self.config.include_query_context:
            metadata.update(
                {
                    "query_length": len(query),
                    "tool_context": tool_context,
                    "available_tools_count": len(available_tools),
                    "primary_tool": tool_context if tool_context in available_tools else "unknown",
                }
            )

        logger.debug(f"Built routing metadata: {metadata}")
        return metadata

    def build_tool_execution_metadata(
        self,
        tool_name: str,
        action: str,
        parameters: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build metadata for tool execution operations.

        Args:
            tool_name: Name of the tool being executed
            action: Action being performed
            parameters: Parameters for the action
            session_id: Optional session identifier

        Returns:
            Dictionary containing metadata for Revenium tracking
        """
        # Generate unique trace ID for this execution
        trace_id = session_id or f"mcp-execution-{uuid.uuid4().hex[:12]}"

        # Build base metadata
        metadata = {
            "product": self.config.product,
            "agent": self.config.agent_type,
            "trace_id": trace_id,
            "task_type": f"tool-execution-{tool_name}-{action}",
            "organization_id": self.config.organization_id,
            "subscription_id": self.config.subscription_id,
        }

        # Add detailed tracking if enabled
        if self.config.enable_detailed_tracking:
            metadata.update(
                {
                    "task_id": f"exec-{uuid.uuid4().hex[:8]}",
                    "tool_name": tool_name,
                    "action": action,
                    "parameter_count": len(parameters),
                    "response_quality_score": 0.95,  # High quality for successful execution
                }
            )

        logger.debug(f"Built tool execution metadata: {metadata}")
        return metadata

    def build_error_metadata(
        self, error_type: str, error_context: str, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build metadata for error tracking.

        Args:
            error_type: Type of error that occurred
            error_context: Context where the error occurred
            session_id: Optional session identifier

        Returns:
            Dictionary containing metadata for Revenium tracking
        """
        # Generate unique trace ID for this error
        trace_id = session_id or f"mcp-error-{uuid.uuid4().hex[:12]}"

        # Build base metadata
        metadata = {
            "product": self.config.product,
            "agent": self.config.agent_type,
            "trace_id": trace_id,
            "task_type": f"error-handling-{error_type}",
            "organization_id": self.config.organization_id,
            "subscription_id": self.config.subscription_id,
        }

        # Add detailed tracking if enabled
        if self.config.enable_detailed_tracking:
            metadata.update(
                {
                    "task_id": f"error-{uuid.uuid4().hex[:8]}",
                    "error_type": error_type,
                    "error_context": error_context,
                    "response_quality_score": 0.1,  # Low quality for errors
                }
            )

        logger.debug(f"Built error metadata: {metadata}")
        return metadata

    def build_custom_metadata(
        self,
        task_type: str,
        custom_fields: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build custom metadata for specific use cases.

        Args:
            task_type: Custom task type identifier
            custom_fields: Additional custom fields to include
            session_id: Optional session identifier

        Returns:
            Dictionary containing metadata for Revenium tracking
        """
        # Generate unique trace ID
        trace_id = session_id or f"mcp-custom-{uuid.uuid4().hex[:12]}"

        # Build base metadata
        metadata = {
            "product": self.config.product,
            "agent": self.config.agent_type,
            "trace_id": trace_id,
            "task_type": task_type,
            "organization_id": self.config.organization_id,
            "subscription_id": self.config.subscription_id,
        }

        # Add custom fields if provided
        if custom_fields:
            metadata.update(custom_fields)

        # Add detailed tracking if enabled
        if self.config.enable_detailed_tracking:
            metadata.setdefault("task_id", f"custom-{uuid.uuid4().hex[:8]}")
            metadata.setdefault("response_quality_score", 0.8)

        logger.debug(f"Built custom metadata: {metadata}")
        return metadata


# Global instance for easy access
default_metadata_builder = ReveniumMetadataBuilder()


def get_metadata_builder() -> ReveniumMetadataBuilder:
    """Get the default metadata builder instance."""
    return default_metadata_builder


def build_routing_metadata(
    query: str, tool_context: str, available_tools: List[str], session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Convenience function for building routing metadata."""
    return default_metadata_builder.build_routing_metadata(
        query, tool_context, available_tools, session_id
    )
