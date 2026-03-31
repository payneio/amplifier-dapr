"""Orchestrator — coordinates multi-service agentic workflows via Dapr."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from amplifier_service_sdk.models import (
    ChatRequest,
    ChatResponse,
    Message,
    RoutingTable,
    ToolCall,
    ToolCapability,
)

from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.hook_dispatcher import HookDispatcher


class Orchestrator:
    """Orchestrates multi-service agentic workflows using the Dapr sidecar."""

    def __init__(self, dapr: DaprClient) -> None:
        """Initialise the Orchestrator.

        Args:
            dapr: Async Dapr HTTP client used for service invocation.
        """
        self._dapr = dapr
        self._hooks = HookDispatcher(dapr=dapr)

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
                Recognised keys:
                - ``max_iterations`` (int, default -1): maximum number of
                  provider-call iterations; -1 means unlimited.
                - ``provider`` (str, default ``"mock"``): key into
                  ``routing_table.providers``.
                - ``tools`` (list, default ``[]``): tool definitions forwarded
                  to the provider inside ``ChatRequest``.
            routing_table: Routing configuration mapping tools/providers/hooks.
            session_id: Optional session identifier used for stream events.

        Returns:
            A tuple of ``(result_text, final_messages)`` where ``result_text``
            is the text content of the last assistant response and
            ``final_messages`` is the conversation as stored in the context
            service after the session ends.
        """
        # ------------------------------------------------------------------
        # Extract config
        # ------------------------------------------------------------------
        max_iterations: int = config.get("max_iterations", -1)
        provider_name: str = config.get("provider", "mock")
        tools_config: list[Any] = config.get("tools", [])

        context_app_id = routing_table.context
        provider_app_id = routing_table.providers.get(provider_name, provider_name)

        # ------------------------------------------------------------------
        # Seed the context service with system prompt + initial messages
        # ------------------------------------------------------------------
        await self._context_add_message(
            context_app_id, {"role": "system", "content": system_prompt}
        )
        for msg in messages:
            await self._context_add_message(context_app_id, msg.model_dump())

        # ------------------------------------------------------------------
        # Convert tool definitions from config to ToolCapability objects
        # ------------------------------------------------------------------
        tools: list[ToolCapability] | None = None
        if tools_config:
            tools = []
            for t in tools_config:
                if isinstance(t, ToolCapability):
                    tools.append(t)
                elif isinstance(t, dict):
                    tools.append(ToolCapability(**t))

        # ------------------------------------------------------------------
        # Main agent loop
        # ------------------------------------------------------------------
        result_text = ""
        iteration = 0

        while True:
            # Enforce max_iterations cap (checked BEFORE each provider call)
            if max_iterations >= 0 and iteration >= max_iterations:
                break

            # Fetch current context window
            context_msgs = await self._context_get_messages(context_app_id)
            chat_messages = [Message(**m) for m in context_msgs]

            # Build and dispatch ChatRequest to provider
            chat_request = ChatRequest(
                messages=chat_messages,
                tools=tools,
                system=system_prompt,
            )
            response_data = await self._call_provider(
                provider_app_id, provider_name, chat_request.model_dump()
            )

            # Parse provider response
            chat_response = ChatResponse(**response_data)
            result_text = self._extract_text(chat_response.content)

            # Publish streaming token event (best-effort)
            await self._publish_stream_event(
                session_id, "stream.token", {"text": result_text}
            )

            # Append assistant message to context
            assistant_msg = Message(
                role="assistant",
                content=chat_response.content,
                tool_calls=chat_response.tool_calls,
            )
            await self._context_add_message(context_app_id, assistant_msg.model_dump())

            iteration += 1

            # No tool calls → we are done
            if not chat_response.tool_calls:
                break

            # Enforce max_iterations AFTER incrementing (avoids redundant
            # tool dispatch on the last allowed iteration)
            if max_iterations >= 0 and iteration >= max_iterations:
                break

            # Dispatch all tool calls in parallel
            tool_result_msgs = await self._dispatch_tools(
                chat_response.tool_calls, routing_table, session_id
            )

            # Persist tool results into context
            for tool_msg in tool_result_msgs:
                await self._context_add_message(context_app_id, tool_msg.model_dump())

        # ------------------------------------------------------------------
        # Return final state
        # ------------------------------------------------------------------
        final_msgs = await self._context_get_messages(context_app_id)
        final_messages = [Message(**m) for m in final_msgs]

        return result_text, final_messages

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    async def _context_add_message(
        self, context_app_id: str, message: dict[str, Any]
    ) -> None:
        """POST a single message to the context service."""
        await self._dapr.invoke(context_app_id, "context/messages", message)

    async def _context_get_messages(self, context_app_id: str) -> list[dict[str, Any]]:
        """GET the current message list from the context service."""
        result = await self._dapr.invoke_get(context_app_id, "context/messages")
        msgs: list[dict[str, Any]] = result.get("messages", [])
        return msgs

    # ------------------------------------------------------------------
    # Provider with retry
    # ------------------------------------------------------------------

    async def _call_provider(
        self,
        provider_app_id: str,
        provider_name: str,
        data: dict[str, Any],
        retries: int = 3,
    ) -> dict[str, Any]:
        """Call the provider service with exponential-backoff retry.

        Args:
            provider_app_id: Dapr app ID of the provider service.
            provider_name: Provider name used to build the endpoint path.
            data: Serialised ``ChatRequest`` payload.
            retries: Number of retry attempts (delays: 1s, 2s, 4s).

        Returns:
            Raw JSON dict from the provider, suitable for ``ChatResponse(**...)``.

        Raises:
            Exception: Re-raises the last exception when all retries are exhausted.
        """
        delays = [1.0, 2.0, 4.0]
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                return await self._dapr.invoke(
                    provider_app_id,
                    f"providers/{provider_name}/complete",
                    data,
                )
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(delays[attempt])

        assert last_error is not None  # unreachable, but satisfies type checker
        raise last_error

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tools(
        self,
        tool_calls: list[ToolCall],
        routing_table: RoutingTable,
        session_id: str,
    ) -> list[Message]:
        """Execute all tool calls in parallel and return result messages.

        Uses ``asyncio.gather`` so calls are concurrent.  Each call is
        guarded by ``_execute_single_tool`` which never raises.
        """
        gathered = await asyncio.gather(
            *[
                self._execute_single_tool(tc, routing_table, session_id)
                for tc in tool_calls
            ]
        )
        return list(gathered)

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        routing_table: RoutingTable,
        session_id: str,
    ) -> Message:
        """Execute a single tool call; errors become error-message strings.

        Never raises — exceptions are caught and returned as a tool Message
        whose content is the error string.
        """
        try:
            # Check if the tool is registered in the routing table
            if tool_call.name not in routing_table.tools:
                return Message(
                    role="tool",
                    content=f"Tool '{tool_call.name}' not found in routing table",
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                )

            tool_app_id = routing_table.tools[tool_call.name]

            # Publish stream.tool_call event
            await self._publish_stream_event(
                session_id,
                "stream.tool_call",
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "arguments": tool_call.arguments,
                },
            )

            # Dispatch pre-hook — block tool if any hook returns DENY
            pre_result = await self._hooks.dispatch_pre(
                "tool:pre",
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "arguments": tool_call.arguments,
                    "session_id": session_id,
                },
                routing_table,
            )
            if pre_result.action == "DENY":
                reason = pre_result.reason or "denied by hook"
                return Message(
                    role="tool",
                    content=f"Tool '{tool_call.name}' was blocked: {reason}",
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                )

            # Invoke the tool service
            raw_result = await self._dapr.invoke(
                tool_app_id,
                f"tools/{tool_call.name}/execute",
                tool_call.arguments,
            )

            # Serialise output to a string
            output: str
            if isinstance(raw_result, str):
                output = raw_result
            else:
                output = json.dumps(raw_result)

            # Dispatch post-hook (best-effort, fire-and-forget)
            await self._hooks.dispatch_post(
                "tool:post",
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "result": output,
                    "session_id": session_id,
                },
            )

            # Publish stream.tool_result event
            await self._publish_stream_event(
                session_id,
                "stream.tool_result",
                {
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "result": output,
                },
            )

            return Message(
                role="tool",
                content=output,
                tool_call_id=tool_call.id,
                name=tool_call.name,
            )

        except Exception as exc:
            error_msg = str(exc)
            return Message(
                role="tool",
                content=error_msg,
                tool_call_id=tool_call.id,
                name=tool_call.name,
            )

    # ------------------------------------------------------------------
    # Pub/Sub streaming
    # ------------------------------------------------------------------

    async def _publish_stream_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Publish a streaming event via Dapr pub/sub.

        Best-effort: exceptions are silently swallowed so the caller never
        fails due to a pub/sub outage.
        """
        try:
            await self._dapr.publish(
                "pubsub",
                event_type,
                {
                    "session_id": session_id,
                    "event_type": event_type,
                    "data": data,
                },
            )
        except Exception:
            pass  # best-effort — never propagates

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _extract_text(self, content: str | list[Any] | None) -> str:
        """Extract plain text from a provider content value.

        Handles:
        - ``None``  → empty string
        - ``str``   → returned as-is
        - ``list``  → concatenation of text blocks (``{"type": "text", "text": "…"}``)
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        # list[dict] — content blocks format
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
        return "".join(texts)
