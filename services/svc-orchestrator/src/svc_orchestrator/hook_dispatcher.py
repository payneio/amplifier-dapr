"""HookDispatcher — dispatches pre/post hook events to registered hook services."""

from __future__ import annotations

import logging
from typing import Any

from amplifier_service_sdk.models import HookResult, RoutingTable

from svc_orchestrator.dapr_client import DaprClient

logger = logging.getLogger(__name__)


class HookDispatcher:
    """Dispatches pre-hook and post-event messages to registered hook services."""

    def __init__(self, dapr: DaprClient) -> None:
        """Initialise the HookDispatcher.

        Args:
            dapr: Async Dapr HTTP client used for service invocation and publishing.
        """
        self._dapr = dapr

    async def dispatch_pre(
        self,
        event: str,
        data: dict[str, Any],
        routing_table: RoutingTable,
    ) -> HookResult:
        """Dispatch a pre-hook event to all registered hook services.

        Chains through each hook in priority order (lower value = higher priority).
        Short-circuits immediately on DENY.  Accumulates INJECT_CONTEXT strings.
        Unreachable hook services are treated as best-effort (logged, not fatal).

        Args:
            event: The event name (e.g. ``"request:pre"``).
            data: Arbitrary payload to pass to each hook.
            routing_table: Routing configuration containing hook registrations.

        Returns:
            A :class:`HookResult` with one of the following actions:

            - ``CONTINUE`` — all hooks approved (or no hooks registered).
            - ``DENY``     — a hook blocked the request.
            - ``INJECT_CONTEXT`` — one or more hooks injected additional context;
              the combined context is in ``result.data["context_injection"]`` and
              ``result.data["ephemeral"]`` is ``True``.
        """
        hook_services: list[str] = routing_table.hooks.get(event, [])

        if not hook_services:
            return HookResult(action="CONTINUE")

        # Sort by priority — lower number runs first; default priority is 50
        sorted_services = sorted(
            hook_services,
            key=lambda app_id: routing_table.hook_priorities.get(app_id, 50),
        )

        context_injections: list[str] = []

        for app_id in sorted_services:
            invoke_path = routing_table.hook_endpoints.get(app_id, "hooks/invoke")
            try:
                raw = await self._dapr.invoke(
                    app_id, invoke_path, {"event": event, "data": data}
                )
                hook_result = HookResult(**raw)
            except Exception:
                logger.warning(
                    "Hook service %r raised an exception for event %r; skipping (best-effort)",
                    app_id,
                    event,
                )
                continue

            if hook_result.action == "DENY":
                return hook_result

            if hook_result.action == "INJECT_CONTEXT":
                injection = (hook_result.data or {}).get("context_injection", "")
                if injection:
                    context_injections.append(str(injection))

        if context_injections:
            return HookResult(
                action="INJECT_CONTEXT",
                data={
                    "context_injection": "\n\n".join(context_injections),
                    "ephemeral": True,
                },
            )

        return HookResult(action="CONTINUE")

    async def dispatch_post(
        self,
        event: str,
        data: dict[str, Any],
    ) -> None:
        """Publish a post-event notification via Dapr pub/sub.

        Converts colons in the event name to dots so the event name is a valid
        Dapr topic name (e.g. ``"stream:token"`` → ``"stream.token"``).

        Best-effort: all exceptions are silently swallowed; this method never
        raises regardless of pub/sub availability.

        Args:
            event: The event name (colons converted to dots for the topic name).
            data: Arbitrary payload to publish.
        """
        topic = event.replace(":", ".")
        try:
            await self._dapr.publish("pubsub", topic, data)
        except Exception:
            pass  # best-effort — never propagates
