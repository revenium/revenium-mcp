"""Fallback router for rule-based query routing.

This module provides rule-based query routing as a fallback mechanism
when AI routing is disabled or fails. It uses pattern matching and
heuristics to route queries to appropriate tools and actions.
"""

import re
from typing import Any, Dict, List, Tuple

from loguru import logger

from .models import ExtractedParameters, RoutingMethod, RoutingResult, RoutingStatus


class FallbackRouter:
    """Rule-based fallback router for query routing.

    Provides reliable rule-based routing using pattern matching and
    heuristics when AI routing is not available or fails.
    """

    def __init__(self):
        """Initialize fallback router with routing patterns."""
        self.routing_patterns = self._build_routing_patterns()
        self.action_patterns = self._build_action_patterns()

        logger.info("Fallback router initialized with rule-based patterns")

    def _build_routing_patterns(self) -> Dict[str, List[Tuple[str, float]]]:
        """Build regex patterns for tool routing.

        Returns:
            Dictionary mapping tools to (pattern, confidence) tuples
        """
        return {
            "products": [
                (r"\b(?:product|plan|pricing|subscription plan)\b", 0.9),
                (r"\bcreate.*(?:product|plan)\b", 0.95),
                (r"\bshow.*(?:products|plans)\b", 0.9),
                (r"\blist.*(?:products|plans)\b", 0.9),
                (r"\bupdate.*(?:product|plan)\b", 0.9),
                (r"\bdelete.*(?:product|plan)\b", 0.9),
            ],
            "alerts": [
                (r"\b(?:alert|notification|alarm)\b", 0.9),
                (r"\bcreate.*alert\b", 0.95),
                (r"\bshow.*alerts?\b", 0.9),
                (r"\blist.*alerts?\b", 0.9),
                (r"\bmy alerts?\b", 0.9),
                (r"\balert.*(?:threshold|condition)\b", 0.85),
            ],
            "subscriptions": [
                (r"\b(?:subscription|billing|invoice)\b", 0.9),
                (r"\bcreate.*subscription\b", 0.95),
                (r"\bshow.*subscriptions?\b", 0.9),
                (r"\blist.*subscriptions?\b", 0.9),
                (r"\bmy subscriptions?\b", 0.9),
                (r"\bbilling.*(?:period|cycle)\b", 0.85),
            ],
            "customers": [
                (r"\b(?:customer|client|user|organization)\b", 0.9),
                (r"\bcreate.*(?:customer|user|organization)\b", 0.95),
                (r"\bshow.*(?:customers?|users?|organizations?)\b", 0.9),
                (r"\blist.*(?:customers?|users?|organizations?)\b", 0.9),
                (r"\bmy (?:customers?|users?|organizations?)\b", 0.9),
                (r"\b(?:add|register).*(?:customer|user)\b", 0.85),
            ],
            "workflows": [
                (r"\b(?:workflow|process|automation)\b", 0.9),
                (r"\bstart.*(?:workflow|process)\b", 0.95),
                (r"\bshow.*(?:workflows?|processes?)\b", 0.9),
                (r"\blist.*(?:workflows?|processes?)\b", 0.9),
                (r"\bnext.*step\b", 0.9),
                (r"\bcomplete.*(?:step|workflow)\b", 0.85),
            ],
        }

    def _build_action_patterns(self) -> Dict[str, List[Tuple[str, float]]]:
        """Build regex patterns for action detection.

        Returns:
            Dictionary mapping actions to (pattern, confidence) tuples
        """
        return {
            "create": [
                (r"\b(?:create|add|new|make|build|setup|register)\b", 0.9),
                (r"\b(?:start|begin|initiate)\b", 0.8),
            ],
            "list": [
                (r"\b(?:list|show|display|get all|view all)\b", 0.9),
                (r"\bshow me (?:all|my)\b", 0.85),
                (r"\bwhat.*(?:do I have|are my)\b", 0.8),
            ],
            "get": [
                (r"\b(?:get|show|display|view|find|lookup)\b", 0.8),
                (r"\bshow me (?:the|this|that)\b", 0.85),
                (r"\bdetails? (?:of|for|about)\b", 0.8),
            ],
            "update": [
                (r"\b(?:update|modify|change|edit|alter)\b", 0.9),
                (r"\bset.*(?:to|as)\b", 0.8),
            ],
            "delete": [
                (r"\b(?:delete|remove|destroy|cancel|terminate)\b", 0.9),
                (r"\bget rid of\b", 0.8),
            ],
            "start": [
                (r"\b(?:start|begin|initiate|launch|trigger)\b", 0.9),
                (r"\bkick off\b", 0.8),
            ],
            "next_step": [
                (r"\bnext.*step\b", 0.95),
                (r"\bwhat.*next\b", 0.8),
                (r"\bcontinue.*(?:workflow|process)\b", 0.85),
            ],
            "complete_step": [
                (r"\bcomplete.*step\b", 0.95),
                (r"\bfinish.*step\b", 0.9),
                (r"\bdone.*(?:with|step)\b", 0.85),
            ],
        }

    async def route_query(self, query: str, tool_context: str) -> RoutingResult:
        """Route query using rule-based patterns.

        Args:
            query: Natural language query to route
            tool_context: Context about the current tool domain

        Returns:
            RoutingResult with tool and action selection
        """
        logger.debug(f"Rule-based routing for query: {query[:100]}...")

        # Normalize query for pattern matching
        normalized_query = query.lower().strip()

        # Determine tool
        tool_name, tool_confidence = self._determine_tool(normalized_query, tool_context)

        # Determine action
        action, action_confidence = self._determine_action(normalized_query, tool_name)

        # Calculate overall confidence
        overall_confidence = min(tool_confidence, action_confidence)

        # Create routing result
        result = RoutingResult(
            tool_name=tool_name,
            action=action,
            parameters=ExtractedParameters(),  # Will be filled by parameter extractor
            confidence=overall_confidence,
            routing_method=RoutingMethod.RULE_BASED,
            status=RoutingStatus.SUCCESS if tool_name and action else RoutingStatus.FAILED,
        )

        if result.status == RoutingStatus.FAILED:
            result.error_message = f"Could not determine tool or action for query: {query[:50]}..."
            logger.warning(f"Rule-based routing failed: {result.error_message}")
        else:
            logger.debug(
                f"Rule-based routing result: {tool_name}.{action} (confidence: {overall_confidence:.2f})"
            )

        return result

    def _determine_tool(self, query: str, tool_context: str) -> Tuple[str, float]:
        """Determine the appropriate tool for the query.

        Args:
            query: Normalized query text
            tool_context: Tool context hint

        Returns:
            Tuple of (tool_name, confidence)
        """
        # If tool context is provided and matches a known tool, use it with high confidence
        if tool_context in self.routing_patterns:
            return tool_context, 0.95

        # Score all tools based on pattern matching
        tool_scores = {}

        for tool, patterns in self.routing_patterns.items():
            max_score = 0.0

            for pattern, confidence in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    max_score = max(max_score, confidence)

            if max_score > 0:
                tool_scores[tool] = max_score

        # Return the highest scoring tool
        if tool_scores:
            best_tool = max(tool_scores.keys(), key=lambda k: tool_scores[k])
            return best_tool, tool_scores[best_tool]

        # Default fallback
        return "products", 0.3  # Low confidence default

    def _determine_action(self, query: str, tool_name: str) -> Tuple[str, float]:
        """Determine the appropriate action for the query.

        Args:
            query: Normalized query text
            tool_name: Selected tool name

        Returns:
            Tuple of (action, confidence)
        """
        # Score all actions based on pattern matching
        action_scores = {}

        for action, patterns in self.action_patterns.items():
            max_score = 0.0

            for pattern, confidence in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    max_score = max(max_score, confidence)

            if max_score > 0:
                action_scores[action] = max_score

        # Apply tool-specific action filtering
        valid_actions = self._get_valid_actions_for_tool(tool_name)
        filtered_scores = {
            action: score for action, score in action_scores.items() if action in valid_actions
        }

        # Return the highest scoring valid action
        if filtered_scores:
            best_action = max(filtered_scores.keys(), key=lambda k: filtered_scores[k])
            return best_action, filtered_scores[best_action]

        # Default action based on tool
        default_action = self._get_default_action_for_tool(tool_name)
        return default_action, 0.5  # Medium confidence default

    def _get_valid_actions_for_tool(self, tool_name: str) -> List[str]:
        """Get valid actions for a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of valid action names
        """
        tool_actions = {
            "products": ["list", "get", "create", "update", "delete"],
            "alerts": ["list", "get", "create", "update", "delete"],
            "subscriptions": ["list", "get", "create", "update", "delete"],
            "customers": ["list", "get", "create", "update", "delete"],
            "workflows": ["list", "get", "start", "next_step", "complete_step"],
        }

        return tool_actions.get(tool_name, ["list", "get", "create", "update", "delete"])

    def _get_default_action_for_tool(self, tool_name: str) -> str:
        """Get default action for a tool when action cannot be determined.

        Args:
            tool_name: Name of the tool

        Returns:
            Default action name
        """
        # Most tools default to 'list' as it's the safest operation
        return "list"

    def get_routing_patterns_summary(self) -> Dict[str, Any]:
        """Get summary of routing patterns for debugging.

        Returns:
            Dictionary containing pattern information
        """
        return {
            "tool_patterns": {
                tool: len(patterns) for tool, patterns in self.routing_patterns.items()
            },
            "action_patterns": {
                action: len(patterns) for action, patterns in self.action_patterns.items()
            },
            "total_patterns": sum(len(patterns) for patterns in self.routing_patterns.values())
            + sum(len(patterns) for patterns in self.action_patterns.values()),
        }
