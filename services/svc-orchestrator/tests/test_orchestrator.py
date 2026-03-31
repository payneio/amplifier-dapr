"""Tests for the Orchestrator agent loop."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dapr() -> DaprClient:
    """Return a DaprClient instance (HTTP calls will be mocked in each test)."""
    return DaprClient(dapr_url="http://localhost:3500")


def _routing_table(
    provider_app_id: str = "svc-provider-mock",
    tools: dict[str, str] | None = None,
    context: str = "svc-context",
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": provider_app_id},
        tools=tools or {},
        context=context,
    )


# ---------------------------------------------------------------------------
# TestOrchestratorTextResponse
# ---------------------------------------------------------------------------


class TestOrchestratorTextResponse:
    """Provider returns a text-only response; loop exits immediately."""

    @pytest.mark.asyncio
    async def test_text_response_returns_result_text(self) -> None:
        """Provider returns text; result_text matches provider content."""
        dapr = _make_dapr()

        # --- mock invoke (context add + provider call) ---
        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Hello from provider!",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            # context/messages add  → just acknowledge
            return {"ok": True}

        # --- mock invoke_get (context get) ---
        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            if "context" in app_id and "messages" in method:
                return {"messages": [{"role": "user", "content": "Hello"}]}
            return {}

        # --- mock publish (best-effort stream events) ---
        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, messages = await orch.execute(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-text-1",
        )

        assert result_text == "Hello from provider!"

    @pytest.mark.asyncio
    async def test_text_response_returns_nonempty_messages(self) -> None:
        """execute() returns a non-empty messages list on text response."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Response text",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {
                "messages": [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Response text"},
                ]
            }

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, messages = await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="Hi")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-text-2",
        )

        assert isinstance(messages, list)
        assert len(messages) > 0

    @pytest.mark.asyncio
    async def test_uses_default_provider_mock(self) -> None:
        """When config has no 'provider' key, defaults to 'mock'."""
        dapr = _make_dapr()
        provider_called = False

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_called
            if app_id == "svc-provider-mock" and "complete" in method:
                provider_called = True
                return {
                    "content": "default provider response",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "test"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="You are helpful.",
            messages=[Message(role="user", content="test")],
            config={},  # no 'provider' key → defaults to 'mock'
            routing_table=_routing_table(),
            session_id="session-default-provider",
        )

        assert provider_called, "Provider 'mock' was never called"
        assert result_text == "default provider response"


# ---------------------------------------------------------------------------
# TestOrchestratorToolLoop
# ---------------------------------------------------------------------------


class TestOrchestratorToolLoop:
    """Provider returns tool_call first, text second; verifies tool dispatch."""

    @pytest.mark.asyncio
    async def test_tool_loop_result_and_call_count(self) -> None:
        """Provider returns tool_call first, text second; call_count == 2."""
        dapr = _make_dapr()
        provider_call_count = 0
        tool_invoked = False

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count, tool_invoked

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    # First call: return tool_call
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-abc",
                                "name": "bash",
                                "arguments": {"cmd": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    # Second call: return text
                    return {
                        "content": "Tool executed successfully!",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-bash" and "tools/bash/execute" in method:
                tool_invoked = True
                return {"output": "hi", "success": True}

            # context add messages
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Run bash"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(tools={"bash": "svc-bash"})
        orch = Orchestrator(dapr=dapr)
        result_text, messages = await orch.execute(
            system_prompt="You are a shell assistant.",
            messages=[Message(role="user", content="Run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-tool-1",
        )

        assert result_text == "Tool executed successfully!"
        assert provider_call_count == 2, (
            f"Expected 2 provider calls, got {provider_call_count}"
        )
        assert tool_invoked, "Tool 'bash' was never invoked"

    @pytest.mark.asyncio
    async def test_tool_error_becomes_error_message_not_exception(self) -> None:
        """Tool invocation failure becomes an error string; execute() does not raise."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {"id": "call-err", "name": "failing_tool", "arguments": {}}
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Recovered after error.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-failing" and "tools/failing_tool/execute" in method:
                raise RuntimeError("tool exploded")

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "use failing tool"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(tools={"failing_tool": "svc-failing"})
        orch = Orchestrator(dapr=dapr)

        # Should NOT raise — tool errors are swallowed and returned as strings
        result_text, messages = await orch.execute(
            system_prompt="You are helpful.",
            messages=[Message(role="user", content="use failing tool")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-tool-error",
        )

        assert result_text == "Recovered after error."


# ---------------------------------------------------------------------------
# TestOrchestratorMaxIterations
# ---------------------------------------------------------------------------


class TestOrchestratorMaxIterations:
    """Loop stops after max_iterations even when provider keeps returning tool calls."""

    @pytest.mark.asyncio
    async def test_max_iterations_limits_provider_calls(self) -> None:
        """With max_iterations=2, provider is called exactly 2 times."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                # Always returns a tool call — never a text response
                return {
                    "content": f"Iteration {provider_call_count}",
                    "tool_calls": [
                        {
                            "id": f"call-{provider_call_count}",
                            "name": "bash",
                            "arguments": {"cmd": "echo loop"},
                        }
                    ],
                    "usage": None,
                    "stop_reason": "tool_use",
                }

            if app_id == "svc-bash" and "tools/bash/execute" in method:
                return {"output": "loop", "success": True}

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Do stuff forever"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(tools={"bash": "svc-bash"})
        orch = Orchestrator(dapr=dapr)

        result_text, messages = await orch.execute(
            system_prompt="You are an infinite loop.",
            messages=[Message(role="user", content="Do stuff forever")],
            config={"provider": "mock", "max_iterations": 2},
            routing_table=routing,
            session_id="session-max-iter",
        )

        assert provider_call_count == 2, (
            f"Expected exactly 2 provider calls with max_iterations=2, "
            f"got {provider_call_count}"
        )

    @pytest.mark.asyncio
    async def test_max_iterations_negative_means_unlimited(self) -> None:
        """max_iterations=-1 does not limit iterations (loop runs until no tool_calls)."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count < 3:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call-{provider_call_count}",
                                "name": "bash",
                                "arguments": {},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    # Third call: text only, terminates loop
                    return {
                        "content": "Done after 3 iterations",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-bash" and "tools/bash/execute" in method:
                return {"output": "ok", "success": True}

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "multi-step"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(tools={"bash": "svc-bash"})
        orch = Orchestrator(dapr=dapr)

        result_text, messages = await orch.execute(
            system_prompt="You run multiple steps.",
            messages=[Message(role="user", content="multi-step")],
            config={"max_iterations": -1},  # unlimited
            routing_table=routing,
            session_id="session-unlimited",
        )

        assert provider_call_count == 3
        assert result_text == "Done after 3 iterations"


# ---------------------------------------------------------------------------
# TestToolDispatchEdgeCases
# ---------------------------------------------------------------------------


class TestToolDispatchEdgeCases:
    """Edge cases: unknown tool names and HTTP errors from tool services."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        """Unknown tool name produces error tool result containing 'not found'; does not raise."""
        dapr = _make_dapr()
        provider_call_count = 0
        context_tool_messages: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-unk",
                                "name": "unknown_tool",
                                "arguments": {},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Handled unknown tool gracefully.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            # Capture tool messages added to context
            if "context" in app_id and "messages" in method:
                if data.get("role") == "tool":
                    context_tool_messages.append(data)
                return {"ok": True}

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "use unknown tool"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        # Routing table has NO entry for 'unknown_tool'
        routing = _routing_table(tools={})
        orch = Orchestrator(dapr=dapr)

        # Should NOT raise
        result_text, messages = await orch.execute(
            system_prompt="You are helpful.",
            messages=[Message(role="user", content="use unknown tool")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-unknown-tool",
        )

        assert result_text == "Handled unknown tool gracefully."
        assert provider_call_count == 2, (
            f"Expected 2 provider calls, got {provider_call_count}"
        )
        assert len(context_tool_messages) >= 1, (
            "Expected at least one tool result message to be added to context"
        )
        assert any(
            "not found" in str(m.get("content", "")).lower()
            for m in context_tool_messages
        ), (
            f"Expected tool result message to contain 'not found', "
            f"got: {context_tool_messages}"
        )

    @pytest.mark.asyncio
    async def test_tool_service_error_returns_error_content(self) -> None:
        """HTTP error from tool service produces error tool result; does not raise."""
        dapr = _make_dapr()
        provider_call_count = 0
        context_tool_messages: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-http-err",
                                "name": "bash",
                                "arguments": {"cmd": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Recovered after HTTP error.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-bash" and "tools/bash/execute" in method:
                # Simulate a 500 HTTP error from the tool service
                request = httpx.Request("POST", "http://svc-bash/tools/bash/execute")
                response = httpx.Response(500, request=request)
                raise httpx.HTTPStatusError(
                    "500 Internal Server Error",
                    request=request,
                    response=response,
                )

            # Capture tool messages added to context
            if "context" in app_id and "messages" in method:
                if data.get("role") == "tool":
                    context_tool_messages.append(data)
                return {"ok": True}

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "run bash"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(tools={"bash": "svc-bash"})
        orch = Orchestrator(dapr=dapr)

        # Should NOT raise
        result_text, messages = await orch.execute(
            system_prompt="You are a shell assistant.",
            messages=[Message(role="user", content="run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-http-error",
        )

        assert result_text == "Recovered after HTTP error."
        assert provider_call_count == 2, (
            f"Expected 2 provider calls, got {provider_call_count}"
        )
        assert len(context_tool_messages) >= 1, (
            "Expected at least one tool result message to be added to context"
        )
        assert any(
            "error" in str(m.get("content", "")).lower() for m in context_tool_messages
        ), (
            f"Expected tool result message to contain 'error', "
            f"got: {context_tool_messages}"
        )
