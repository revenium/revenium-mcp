"""Schema Discovery Package.

This package contains schema discovery and capabilities functionality.
Each module handles schema discovery for a specific resource type.
"""

# Backward compatibility - import from original schema_discovery.py
from ..schema_discovery import SchemaDiscoveryEngine as LegacySchemaDiscoveryEngine

# Import resource-specific discoverers
from .alert_schema import AlertSchemaDiscovery

# Import core discovery engine
from .discovery_engine import BaseSchemaDiscovery, SchemaDiscoveryEngine, schema_discovery_engine
from .source_schema import SourceSchemaDiscovery

# Auto-register discoverers
schema_discovery_engine.register_discoverer("anomalies", AlertSchemaDiscovery())
schema_discovery_engine.register_discoverer("alerts", AlertSchemaDiscovery())
schema_discovery_engine.register_discoverer("sources", SourceSchemaDiscovery())

__all__ = [
    # Core engine
    "BaseSchemaDiscovery",
    "SchemaDiscoveryEngine",
    "schema_discovery_engine",
    # Resource-specific discoverers
    "AlertSchemaDiscovery",
    # Backward compatibility
    "LegacySchemaDiscoveryEngine",
]
