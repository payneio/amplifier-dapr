"""Orchestrator — coordinates multi-service agentic workflows via Dapr."""

from __future__ import annotations

from typing import Any

from amplifier_service_sdk.models import Message, RoutingTable

from svc_orchestrator.dapr_client import DaprClient


class Orchestrator:
    """Orchestrates multi-service agentic workflows using the Dapr sidecar.

    This is a stub implementation. The execute() method raises NotImplementedError
    until the full orchestration logic is implemented.
    """

    def __init__(self, dapr: DaprClient) -> None:
        """Initialise the Orchestrator.

        Args:
            dapr: Async Dapr HTTP client used for service invocation.
        """
        self._dapr = dapr

    async def execute(
        self,
        system_prompt: str,
        messages: list[Message],
        config: dict[str, Any],
        routing_table: RoutingTable,
        session_id: str = "",
    ) -> tuple[str, list[Message]]:
        """Execute an orchestration session.

        Args:
            system_prompt: System prompt for the session.
            messages: Conversation history as a list of Message objects.
            config: Arbitrary configuration dict for the session.
            routing_table: Routing configuration mapping tools/providers/hooks.
            session_id: Optional session identifier for resumability.

        Returns:
            A tuple of (result_text, updated_messages).

        Raises:
            NotImplementedError: Always — stub implementation.
        """
        raise NotImplementedError("Orchestrator.execute() is not yet implemented")
