"""Discovery module for session-service — resolves available services into a routing table."""

from __future__ import annotations

from amplifier_service_sdk.models import RoutingTable


def discover_services(services: list[str]) -> RoutingTable:
    """Discover available services and return a minimal routing table.

    Args:
        services: List of requested service names.

    Returns:
        A minimal RoutingTable stub for use in orchestrator requests.
    """
    return RoutingTable()
