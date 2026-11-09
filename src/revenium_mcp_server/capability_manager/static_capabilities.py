"""The built-in capability table, served where the dynamic capability service never starts."""

from typing import AbstractSet, Any, Dict, List, Optional

from ..exceptions import ValidationError
from .discovery import CapabilityDiscovery

SUPPORTED_RESOURCE_TYPES = frozenset(
    {
        "system",
        "products",
        "subscriptions",
        "customers",
        "alerts",
        "sources",
        "metering_elements",
        "metering",
    }
)

STATIC_CAPABILITIES_NOTE = (
    "This is the static capability set: a server that serves many customers "
    "(Clerk/OAuth or per-request API key) does not start the dynamic capability "
    "service, so it answers from its built-in table."
)


def require_supported_resource_type(
    resource_type: str, supported: AbstractSet[str] = SUPPORTED_RESOURCE_TYPES
) -> None:
    """Refuse a resource type outside ``supported`` before any capability lookup."""
    if resource_type not in supported:
        raise ValidationError(
            message=f"Unsupported resource type: {resource_type}",
            field="resource_type",
            value=resource_type,
            expected=f"One of: {', '.join(sorted(supported))}",
        )


async def static_capabilities(resource_type: str) -> Dict[str, Any]:
    """Return the built-in capability table for a supported resource type."""
    require_supported_resource_type(resource_type)
    return await CapabilityDiscovery().static_capabilities(resource_type)


def _model_names(model_samples: List[str]) -> List[str]:
    return [entry.split("/", 1)[1] if "/" in entry else entry for entry in model_samples]


def _listed_values(
    capabilities: Dict[str, Any], resource_type: str, capability_name: str
) -> Optional[List[str]]:
    if resource_type == "metering":
        if capability_name == "providers" and "provider_summary" in capabilities:
            return list(capabilities["provider_summary"].get("samples", []))
        if capability_name == "models" and "model_summary" in capabilities:
            return _model_names(capabilities["model_summary"].get("samples", []))

    values = capabilities.get(capability_name)
    if isinstance(values, dict):
        values = values.get("all")
    return list(values) if isinstance(values, list) else None


def static_verdict(
    capabilities: Dict[str, Any], resource_type: str, capability_name: str, value: str
) -> Optional[bool]:
    """Decide a value only against a listed set of values, or None when the table lists none."""
    listed = _listed_values(capabilities, resource_type, capability_name)
    return None if listed is None else value in listed


def checkable_capability_names(capabilities: Dict[str, Any], resource_type: str) -> List[str]:
    """Names of the capabilities whose accepted values the table lists."""
    return sorted(
        name
        for name in capabilities
        if _listed_values(capabilities, resource_type, name) is not None
    )
