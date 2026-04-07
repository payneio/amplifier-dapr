"""Tests for the Orchestrator agent loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

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
    tools: dict[str, str] | None = None,
    hooks: dict[str, list[str]] | None = None,
    provider_app_id: str = "svc-provider-mock",
    context: str = "svc-context",
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": provider_app_id},
        tools=tools or {},
        context=context,
        hooks=hooks or {},
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

            if app_id == "svc-machine" and "tools/bash/execute" in method:
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

        routing = _routing_table(tools={"bash": "svc-machine"})
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

            if app_id == "svc-machine" and "tools/bash/execute" in method:
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

        routing = _routing_table(tools={"bash": "svc-machine"})
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

            if app_id == "svc-machine" and "tools/bash/execute" in method:
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

        routing = _routing_table(tools={"bash": "svc-machine"})
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

            if app_id == "svc-machine" and "tools/bash/execute" in method:
                # Simulate a 500 HTTP error from the tool service
                request = httpx.Request("POST", "http://svc-machine/tools/bash/execute")
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

        routing = _routing_table(tools={"bash": "svc-machine"})
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


# ---------------------------------------------------------------------------
# TestProviderRetry
# ---------------------------------------------------------------------------


class TestProviderRetry:
    """Provider dispatch retries on transient failures with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self) -> None:
        """Provider raises ConnectionError on first call, succeeds on second; invoke_call_count==2."""
        dapr = _make_dapr()
        invoke_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal invoke_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                invoke_call_count += 1
                if invoke_call_count == 1:
                    raise ConnectionError("transient network failure")
                return {
                    "content": "Recovered after retry",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hello"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)

        with patch(
            "svc_orchestrator.orchestrator.asyncio.sleep", new_callable=AsyncMock
        ):
            result_text, _ = await orch.execute(
                system_prompt="You are a helpful assistant.",
                messages=[Message(role="user", content="Hello")],
                config={"provider": "mock"},
                routing_table=_routing_table(),
                session_id="session-retry-1",
            )

        assert "Recovered" in result_text
        assert invoke_call_count == 2, (
            f"Expected 2 provider invoke calls (1 failed + 1 succeeded), "
            f"got {invoke_call_count}"
        )


# ---------------------------------------------------------------------------
# TestOrchestratorPreHookDeny
# ---------------------------------------------------------------------------


class TestOrchestratorPreHookDeny:
    """When a pre-hook denies a tool, the tool service must NOT be invoked."""

    @pytest.mark.asyncio
    async def test_pre_hook_deny_prevents_tool_invocation(self) -> None:
        """When pre-hook denies, tool is NOT invoked and result contains denial reason."""
        dapr = _make_dapr()
        invocation_log: list[str] = []
        provider_call_count = 0
        context_tool_messages: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count
            invocation_log.append(app_id)

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-deny",
                                "name": "bash",
                                "arguments": {"cmd": "rm -rf /"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Tool was blocked.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            # Hook service returns DENY
            if app_id == "svc-guard-hook":
                return {
                    "action": "DENY",
                    "reason": "Tool use blocked by guard",
                    "data": None,
                }

            # Capture tool messages added to context
            if "context" in app_id and "messages" in method:
                if isinstance(data, dict) and data.get("role") == "tool":
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

        # Routing table with 'tool:pre' hook pointing to guard service
        routing = _routing_table(
            tools={"bash": "svc-machine"},
            hooks={"tool:pre": ["svc-guard-hook"]},
        )
        orch = Orchestrator(dapr=dapr)

        result_text, messages = await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-deny-1",
        )

        assert "svc-machine" not in invocation_log, (
            "Tool service 'svc-machine' should NOT have been invoked when pre-hook denies"
        )
        assert len(context_tool_messages) >= 1, (
            "Expected at least one tool result message in context (the denial message)"
        )
        assert any(
            "blocked" in str(m.get("content", "")).lower()
            for m in context_tool_messages
        ), (
            f"Expected tool result message to contain 'blocked', "
            f"got: {context_tool_messages}"
        )

    @pytest.mark.asyncio
    async def test_pre_hook_deny_reason_in_tool_result(self) -> None:
        """Denial reason from hook is included in the returned tool message content."""
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
                            {"id": "call-deny2", "name": "bash", "arguments": {}}
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Handled denial.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-policy-hook":
                return {
                    "action": "DENY",
                    "reason": "policy violation detected",
                    "data": None,
                }

            if "context" in app_id and "messages" in method:
                if isinstance(data, dict) and data.get("role") == "tool":
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

        routing = _routing_table(
            tools={"bash": "svc-machine"},
            hooks={"tool:pre": ["svc-policy-hook"]},
        )
        orch = Orchestrator(dapr=dapr)

        await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-deny-2",
        )

        assert len(context_tool_messages) >= 1
        # The denial reason should appear in the tool message content
        assert any(
            "policy violation detected" in str(m.get("content", ""))
            for m in context_tool_messages
        ), f"Expected denial reason in tool message, got: {context_tool_messages}"


# ---------------------------------------------------------------------------
# TestOrchestratorPostHookPublish
# ---------------------------------------------------------------------------


class TestOrchestratorPostHookPublish:
    """After tool execution, dispatch_post publishes a 'tool.post' event."""

    @pytest.mark.asyncio
    async def test_post_hook_publishes_tool_post_topic(self) -> None:
        """After tool execution, 'tool.post' appears in published_topics list."""
        dapr = _make_dapr()
        published_topics: list[str] = []
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
                            {
                                "id": "call-post",
                                "name": "bash",
                                "arguments": {"cmd": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Done.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-machine" and "tools/bash/execute" in method:
                return {"output": "hi", "success": True}

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "run bash"}]}

        async def mock_publish(
            pubsub: str, topic: str, data: Any, **kwargs: Any
        ) -> None:
            published_topics.append(topic)

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(tools={"bash": "svc-machine"})
        orch = Orchestrator(dapr=dapr)

        result_text, messages = await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-post-hook-1",
        )

        assert result_text == "Done."
        assert "tool.post" in published_topics, (
            f"Expected 'tool.post' in published topics, got: {published_topics}"
        )


# ---------------------------------------------------------------------------
# TestOrchestratorProviderRequestHook
# ---------------------------------------------------------------------------


class TestOrchestratorProviderRequestHook:
    """dispatch_pre is called with 'provider:request' before each provider call."""

    @pytest.mark.asyncio
    async def test_provider_request_hook_called_before_each_provider_call(
        self,
    ) -> None:
        """dispatch_pre is called with 'provider:request' before each provider call."""
        dapr = _make_dapr()
        hook_call_events: list[str] = []
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            # Hook service — record the event name from the payload
            if app_id == "svc-request-hook":
                hook_call_events.append(data.get("event", ""))
                return {"action": "CONTINUE", "reason": None, "data": None}

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "name": "bash",
                                "arguments": {"cmd": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Done.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-machine" and "tools/bash/execute" in method:
                return {"output": "hi", "success": True}

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

        routing = _routing_table(
            tools={"bash": "svc-machine"},
            hooks={"provider:request": ["svc-request-hook"]},
        )
        orch = Orchestrator(dapr=dapr)

        result_text, _ = await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-provider-hook-1",
        )

        assert result_text == "Done."
        # provider:request hook should have been called once per provider call (2 total)
        assert hook_call_events.count("provider:request") == 2, (
            f"Expected 'provider:request' hook called 2 times, got: {hook_call_events}"
        )

    @pytest.mark.asyncio
    async def test_provider_request_hook_inject_context_prepends_system_prompt(
        self,
    ) -> None:
        """When hook returns INJECT_CONTEXT, injection is prepended to system_prompt in ChatRequest."""
        dapr = _make_dapr()
        captured_chat_requests: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            # Hook service — inject context
            if app_id == "svc-inject-hook":
                return {
                    "action": "INJECT_CONTEXT",
                    "reason": None,
                    "context_injection": "INJECTED_CONTEXT",
                    "ephemeral": True,
                }

            if app_id == "svc-provider-mock" and "complete" in method:
                # Capture the ChatRequest to verify system prompt
                captured_chat_requests.append(data)
                return {
                    "content": "Done.",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }

            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "hello"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = _routing_table(
            hooks={"provider:request": ["svc-inject-hook"]},
        )
        orch = Orchestrator(dapr=dapr)

        await orch.execute(
            system_prompt="BASE_PROMPT",
            messages=[Message(role="user", content="hello")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-inject-1",
        )

        assert len(captured_chat_requests) == 1
        system_in_request = captured_chat_requests[0].get("system", "")
        assert system_in_request.startswith("INJECTED_CONTEXT\n\n"), (
            f"Expected system to start with injection, got: {system_in_request!r}"
        )
        assert "BASE_PROMPT" in system_in_request, (
            f"Expected base prompt in system, got: {system_in_request!r}"
        )


# ---------------------------------------------------------------------------
# TestOrchestratorSessionEvents
# ---------------------------------------------------------------------------


class TestOrchestratorSessionEvents:
    """'session.start' and 'session.end' are published when execute() runs."""

    @pytest.mark.asyncio
    async def test_session_start_and_end_published(self) -> None:
        """'session.start' and 'session.end' appear in published_topics after execute()."""
        dapr = _make_dapr()
        published_topics: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Hello!",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hello"}]}

        async def mock_publish(
            pubsub: str, topic: str, data: Any, **kwargs: Any
        ) -> None:
            published_topics.append(topic)

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-events-1",
        )

        assert result_text == "Hello!"
        assert "session.start" in published_topics, (
            f"Expected 'session.start' in published topics, got: {published_topics}"
        )
        assert "session.end" in published_topics, (
            f"Expected 'session.end' in published topics, got: {published_topics}"
        )

    @pytest.mark.asyncio
    async def test_session_start_published_before_provider_calls(self) -> None:
        """'session.start' is published at the very beginning (before any provider call)."""
        dapr = _make_dapr()
        event_order: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                event_order.append("provider_call")
                return {
                    "content": "Done.",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hello"}]}

        async def mock_publish(
            pubsub: str, topic: str, data: Any, **kwargs: Any
        ) -> None:
            if topic in ("session.start", "session.end"):
                event_order.append(topic)

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="Be helpful.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-events-2",
        )

        # session.start must come before any provider call
        # session.end must come after all provider calls
        assert "session.start" in event_order
        assert "session.end" in event_order
        # .index() is safe: presence confirmed by asserts above
        start_idx = event_order.index("session.start")
        end_idx = event_order.index("session.end")
        provider_idx = event_order.index("provider_call")
        assert start_idx < provider_idx, (
            f"Expected session.start before provider_call, got order: {event_order}"
        )
        assert provider_idx < end_idx, (
            f"Expected provider_call before session.end, got order: {event_order}"
        )


# ---------------------------------------------------------------------------
# TestContextURLPaths - session_id in URL paths
# ---------------------------------------------------------------------------


class TestContextURLPaths:
    """Context service URLs include session_id in the path."""

    @pytest.mark.asyncio
    async def test_context_add_uses_session_keyed_path(self) -> None:
        """_context_add_message should use context/{session_id}/messages path."""
        dapr = _make_dapr()
        context_invoke_paths: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context":
                context_invoke_paths.append(method)
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Done!",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hello"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="You are helpful.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="test-session-abc",
        )

        # All context POSTs must use the session-keyed path
        assert len(context_invoke_paths) > 0, "No context invoke calls recorded"
        for path in context_invoke_paths:
            assert path == "context/test-session-abc/messages", (
                f"Expected 'context/test-session-abc/messages', got {path!r}"
            )

    @pytest.mark.asyncio
    async def test_context_get_uses_session_keyed_path(self) -> None:
        """_context_get_messages should use context/{session_id}/messages path."""
        dapr = _make_dapr()
        context_get_paths: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Done!",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context":
                context_get_paths.append(method)
            return {"messages": [{"role": "user", "content": "Hello"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="You are helpful.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="test-session-xyz",
        )

        # All context GETs must use the session-keyed path
        assert len(context_get_paths) > 0, "No context invoke_get calls recorded"
        for path in context_get_paths:
            assert path == "context/test-session-xyz/messages", (
                f"Expected 'context/test-session-xyz/messages', got {path!r}"
            )


# ---------------------------------------------------------------------------
# TestMachineInstanceIdForwarding
# ---------------------------------------------------------------------------


class TestMachineInstanceIdForwarding:
    """machine_instance_id is forwarded in every tool dispatch request body."""

    @pytest.mark.asyncio
    async def test_tool_dispatch_includes_machine_instance_id(self) -> None:
        """When machine_instance_id='inst-xyz789', it appears in tool dispatch body."""
        dapr = _make_dapr()
        provider_call_count = 0
        tool_invoke_payloads: list[dict[str, Any]] = []

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
                                "id": "call-mid-1",
                                "name": "bash",
                                "arguments": {"cmd": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Done.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-machine" and "tools/bash/execute" in method:
                tool_invoke_payloads.append(data)
                return {"output": "hi", "success": True}

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

        routing = _routing_table(tools={"bash": "svc-machine"})
        orch = Orchestrator(dapr=dapr)

        await orch.execute(
            system_prompt="You are a shell assistant.",
            messages=[Message(role="user", content="Run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-mid-1",
            machine_instance_id="inst-xyz789",
        )

        assert len(tool_invoke_payloads) == 1, (
            f"Expected exactly 1 tool invocation, got {len(tool_invoke_payloads)}"
        )
        assert tool_invoke_payloads[0].get("machine_instance_id") == "inst-xyz789", (
            f"Expected machine_instance_id='inst-xyz789', "
            f"got: {tool_invoke_payloads[0]}"
        )

    @pytest.mark.asyncio
    async def test_tool_dispatch_without_machine_instance_id(self) -> None:
        """When no machine_instance_id is provided, None appears in tool dispatch body."""
        dapr = _make_dapr()
        provider_call_count = 0
        tool_invoke_payloads: list[dict[str, Any]] = []

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
                                "id": "call-mid-2",
                                "name": "bash",
                                "arguments": {"cmd": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Done.",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-machine" and "tools/bash/execute" in method:
                tool_invoke_payloads.append(data)
                return {"output": "hi", "success": True}

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

        routing = _routing_table(tools={"bash": "svc-machine"})
        orch = Orchestrator(dapr=dapr)

        # No machine_instance_id kwarg
        await orch.execute(
            system_prompt="You are a shell assistant.",
            messages=[Message(role="user", content="Run bash")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-mid-2",
        )

        assert len(tool_invoke_payloads) == 1, (
            f"Expected exactly 1 tool invocation, got {len(tool_invoke_payloads)}"
        )
        assert tool_invoke_payloads[0].get("machine_instance_id") is None, (
            f"Expected machine_instance_id=None, got: {tool_invoke_payloads[0]}"
        )
