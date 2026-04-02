"""Discovery module for session-service — resolves available services into a routing table."""

from __future__ import annotations

import logging
from typing import Any

import httpx


logger = logging.getLogger(__name__)


async def _call_describe(app_id: str, dapr_url: str) -> dict[str, Any]:
    """GET /describe from a service via Dapr Service Invocation.

    Args:
        app_id: Dapr app-id of the target service.
        dapr_url: Base URL of the Dapr HTTP sidecar.

    Returns:
        The parsed JSON response body from the /describe endpoint.
    """
    url = f"{dapr_url}/v1.0/invoke/{app_id}/method/describe"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def build_routing_table(
    describe_results: dict[str, dict[str, Any]],
    context_app_id: str,
) -> dict[str, Any]:
    """Build a routing table from a map of describe responses.

    Args:
        describe_results: Mapping of app_id -> describe response dict.
        context_app_id: App-id of the context service to include in the table.

    Returns:
        A routing table dict with keys:
        - 'tools': {tool_name: app_id}
        - 'providers': {provider_name: app_id}
        - 'hooks': {event: [app_id, ...]}
        - '_tool_specs': list of raw tool spec dicts
        - '_modes': list of raw mode spec dicts
        - '_agents': list of raw agent spec dicts
        - 'context': context_app_id
    """
    tools: dict[str, str] = {}
    providers: dict[str, str] = {}
    hooks: dict[str, list[str]] = {}
    hook_endpoints: dict[str, str] = {}
    hook_priorities: dict[str, int] = {}
    tool_specs: list[dict[str, Any]] = []
    modes: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []

    for app_id, describe in describe_results.items():
        # Map tools: tool_name -> app_id
        for tool in describe.get("tools", []):
            name = tool.get("name")
            if name:
                tools[name] = app_id
                tool_specs.append(tool)

        # Collect modes advertised by this service
        for mode in describe.get("modes", []):
            modes.append(mode)

        # Collect agents advertised by this service
        for agent in describe.get("agents", []):
            agents.append(agent)

        # Map providers: provider_name -> app_id
        for provider in describe.get("providers", []):
            name = provider.get("name")
            if name:
                providers[name] = app_id

        # Map hooks: expand events list -> each event -> [app_id, ...]
        # Only sync hooks (mode == 'sync' or no mode) are added to the routing table.
        # Async hooks (mode == 'async') subscribe via Dapr pub/sub directly — skip them.
        for hook in describe.get("hooks", []):
            mode: str = hook.get("mode", "sync")
            if mode == "async":
                continue

            hook_name: str = hook.get("name", "")
            events: list[str] = hook.get("events", [])
            for event in events:
                if event not in hooks:
                    hooks[event] = []
                hooks[event].append(app_id)

            # Register the endpoint and priority for this sync hook service
            if hook_name:
                hook_endpoints[app_id] = f"hooks/{hook_name}/invoke"
            hook_priorities[app_id] = hook.get(
                "priority", 50
            )  # matches HookRegistration.priority default

    # Collect content paths advertised by each service
    content_services: dict[str, list[str]] = {}
    for app_id, describe in describe_results.items():
        paths = describe.get("content_paths", [])
        if paths:
            content_services[app_id] = paths

    return {
        "tools": tools,
        "providers": providers,
        "hooks": hooks,
        "hook_endpoints": hook_endpoints,
        "hook_priorities": hook_priorities,
        "_tool_specs": tool_specs,
        "_modes": modes,
        "_agents": agents,
        "_content_services": content_services,
        "context": context_app_id,
    }


async def discover_services(
    service_app_ids: list[str],
    dapr_url: str,
    context_app_id: str = "svc-context",
) -> dict[str, Any]:
    """Call /describe on each service and build a routing table.

    Services that fail to respond are logged as warnings and skipped.

    Args:
        service_app_ids: List of Dapr app-ids to interrogate.
        dapr_url: Base URL of the Dapr HTTP sidecar.
        context_app_id: App-id of the context service (default: 'svc-context').

    Returns:
        A routing table dict (see build_routing_table for structure).
    """
    describe_results: dict[str, dict[str, Any]] = {}

    for app_id in service_app_ids:
        try:
            result = await _call_describe(app_id, dapr_url)
            describe_results[app_id] = result
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to describe service %r: %s", app_id, exc)

    return build_routing_table(describe_results, context_app_id)
