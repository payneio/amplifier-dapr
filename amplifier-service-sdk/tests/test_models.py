"""Tests for Pydantic v2 models in amplifier_service_sdk."""

import json

from amplifier_service_sdk import (
    ContentFile,
    DescribeResponse,
    HealthResponse,
    HookEvent,
    HookResult,
    ModeCapability,
    ProviderRequest,
    ProviderResponse,
    ToolCapability,
    ToolRequest,
    ToolResult,
)


class TestToolResult:
    def test_success_default(self):
        result = ToolResult()
        assert result.success is True
        assert result.output is None
        assert result.error is None

    def test_failure(self):
        result = ToolResult(
            success=False, error={"code": "NOT_FOUND", "message": "Tool not found"}
        )
        assert result.success is False
        assert result.error == {"code": "NOT_FOUND", "message": "Tool not found"}

    def test_json_roundtrip(self):
        original = ToolResult(
            success=False, output="some output", error={"code": "ERR"}
        )
        dumped = json.loads(original.model_dump_json())
        recovered = ToolResult.model_validate(dumped)
        assert recovered.success == original.success
        assert recovered.output == original.output
        assert recovered.error == original.error


class TestToolRequest:
    def test_basic(self):
        req = ToolRequest(name="my_tool", input={"key": "value"})
        assert req.name == "my_tool"
        assert req.input == {"key": "value"}

    def test_empty_input_default(self):
        req = ToolRequest(name="my_tool")
        assert req.name == "my_tool"
        assert req.input == {}


class TestToolCapability:
    def test_fields(self):
        cap = ToolCapability(
            name="search",
            description="Search the web",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        )
        assert cap.name == "search"
        assert cap.description == "Search the web"
        assert "query" in cap.input_schema["properties"]

    def test_defaults(self):
        cap = ToolCapability(name="my_tool")
        assert cap.description == ""
        assert cap.input_schema == {}


class TestModeCapability:
    def test_fields(self):
        mode = ModeCapability(name="plan", description="Think and discuss")
        assert mode.name == "plan"
        assert mode.description == "Think and discuss"

    def test_description_defaults_to_empty(self):
        mode = ModeCapability(name="review")
        assert mode.name == "review"
        assert mode.description == ""

    def test_json_roundtrip(self):
        original = ModeCapability(name="strict", description="Strict mode")
        dumped = json.loads(original.model_dump_json())
        recovered = ModeCapability.model_validate(dumped)
        assert recovered.name == original.name
        assert recovered.description == original.description


class TestDescribeResponse:
    def test_minimal(self):
        resp = DescribeResponse(name="my-service")
        assert resp.name == "my-service"
        assert resp.version == "0.1.0"
        assert resp.tools == []
        assert resp.hooks == []
        assert resp.providers == []
        assert resp.content_paths == []
        assert resp.modes == []

    def test_with_tools(self):
        tool = ToolCapability(name="do_thing", description="Does the thing")
        resp = DescribeResponse(name="my-service", tools=[tool])
        assert len(resp.tools) == 1
        assert resp.tools[0].name == "do_thing"

    def test_with_modes(self):
        modes = [
            ModeCapability(name="plan", description="Think and discuss"),
            ModeCapability(name="review", description="Code review mode"),
        ]
        resp = DescribeResponse(name="svc-modes", modes=modes)
        assert len(resp.modes) == 2
        assert resp.modes[0].name == "plan"
        assert resp.modes[1].name == "review"

    def test_json_roundtrip_with_modes(self):
        modes = [ModeCapability(name="strict", description="Strict mode")]
        original = DescribeResponse(name="svc", version="1.2.3", modes=modes)
        dumped = json.loads(original.model_dump_json())
        recovered = DescribeResponse.model_validate(dumped)
        assert recovered.name == "svc"
        assert len(recovered.modes) == 1
        assert recovered.modes[0].name == "strict"
        assert recovered.modes[0].description == "Strict mode"

    def test_json_roundtrip(self):
        tool = ToolCapability(name="search", description="Search")
        original = DescribeResponse(name="svc", version="1.2.3", tools=[tool])
        dumped = json.loads(original.model_dump_json())
        recovered = DescribeResponse.model_validate(dumped)
        assert recovered.name == "svc"
        assert recovered.version == "1.2.3"
        assert len(recovered.tools) == 1
        assert recovered.tools[0].name == "search"


class TestHealthResponse:
    def test_defaults(self):
        resp = HealthResponse(service_name="my-svc")
        assert resp.status == "healthy"
        assert resp.service_name == "my-svc"
        assert resp.version == "0.1.0"

    def test_custom_status(self):
        resp = HealthResponse(service_name="my-svc", status="degraded", version="2.0.0")
        assert resp.status == "degraded"
        assert resp.version == "2.0.0"


class TestContentFile:
    def test_fields(self):
        cf = ContentFile(path="docs/README.md", content="# Hello")
        assert cf.path == "docs/README.md"
        assert cf.content == "# Hello"


class TestHookEvent:
    def test_fields(self):
        evt = HookEvent(event="tool:before", data={"tool": "search"})
        assert evt.event == "tool:before"
        assert evt.data == {"tool": "search"}

    def test_empty_data_default(self):
        evt = HookEvent(event="tool:before")
        assert evt.data == {}


class TestHookResult:
    def test_defaults(self):
        result = HookResult()
        assert result.action == "CONTINUE"
        assert result.data is None
        assert result.reason is None

    def test_custom_fields(self):
        result = HookResult(action="BLOCK", data={"key": "val"}, reason="Not allowed")
        assert result.action == "BLOCK"
        assert result.data == {"key": "val"}
        assert result.reason == "Not allowed"


class TestProviderRequest:
    def test_fields(self):
        req = ProviderRequest(
            messages=[{"role": "user", "content": "Hello"}],
            tools=[{"name": "search"}],
            system="You are helpful",
            max_output_tokens=1024,
            temperature=0.7,
        )
        assert len(req.messages) == 1
        assert req.messages[0]["role"] == "user"
        assert req.tools == [{"name": "search"}]
        assert req.system == "You are helpful"
        assert req.max_output_tokens == 1024
        assert req.temperature == 0.7

    def test_optional_fields_default_none(self):
        req = ProviderRequest(messages=[{"role": "user", "content": "Hi"}])
        assert req.tools is None
        assert req.system is None
        assert req.max_output_tokens is None
        assert req.temperature is None


class TestProviderResponse:
    def test_fields(self):
        resp = ProviderResponse(
            content="Hello there",
            tool_calls=[{"name": "search", "input": {}}],
            usage={"input_tokens": 10, "output_tokens": 20},
        )
        assert resp.content == "Hello there"
        assert resp.tool_calls == [{"name": "search", "input": {}}]
        assert resp.usage == {"input_tokens": 10, "output_tokens": 20}

    def test_optional_fields_default_none(self):
        resp = ProviderResponse()
        assert resp.content is None
        assert resp.tool_calls is None
        assert resp.usage is None

    def test_content_as_list(self):
        resp = ProviderResponse(content=[{"type": "text", "text": "hello"}])
        assert isinstance(resp.content, list)
        assert resp.content[0]["type"] == "text"


# ── Phase 2 model tests ──────────────────────────────────────────────────────


class TestHookAction:
    def test_enum_values(self):
        from amplifier_service_sdk import HookAction

        assert HookAction.CONTINUE == "CONTINUE"
        assert HookAction.DENY == "DENY"
        assert HookAction.MODIFY == "MODIFY"
        assert HookAction.INJECT_CONTEXT == "INJECT_CONTEXT"

    def test_is_str(self):
        from amplifier_service_sdk import HookAction

        assert isinstance(HookAction.CONTINUE, str)

    def test_membership(self):
        from amplifier_service_sdk import HookAction

        values = [e.value for e in HookAction]
        assert set(values) == {"CONTINUE", "DENY", "MODIFY", "INJECT_CONTEXT"}


class TestToolCall:
    def test_basic_fields(self):
        from amplifier_service_sdk import ToolCall

        tc = ToolCall(id="call_1", name="search", arguments={"query": "hello"})
        assert tc.id == "call_1"
        assert tc.name == "search"
        assert tc.arguments == {"query": "hello"}

    def test_arguments_default_empty_dict(self):
        from amplifier_service_sdk import ToolCall

        tc = ToolCall(id="call_2", name="noop")
        assert tc.arguments == {}

    def test_json_roundtrip(self):
        from amplifier_service_sdk import ToolCall

        original = ToolCall(id="x", name="y", arguments={"k": "v"})
        dumped = json.loads(original.model_dump_json())
        recovered = ToolCall.model_validate(dumped)
        assert recovered.id == original.id
        assert recovered.name == original.name
        assert recovered.arguments == original.arguments


class TestTokenUsage:
    def test_defaults(self):
        from amplifier_service_sdk import TokenUsage

        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_custom_values(self):
        from amplifier_service_sdk import TokenUsage

        usage = TokenUsage(input_tokens=100, output_tokens=250)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 250


class TestMessage:
    def test_minimal(self):
        from amplifier_service_sdk import Message

        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None
        assert msg.tool_call_id is None
        assert msg.name is None
        assert msg.metadata is None

    def test_all_fields(self):
        from amplifier_service_sdk import Message, ToolCall

        tc = ToolCall(id="c1", name="search")
        msg = Message(
            role="assistant",
            content=None,
            tool_calls=[tc],
            tool_call_id="tc_id",
            name="bot",
            metadata={"key": "val"},
        )
        assert msg.role == "assistant"
        assert msg.content is None
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_call_id == "tc_id"
        assert msg.name == "bot"
        assert msg.metadata == {"key": "val"}

    def test_content_as_list(self):
        from amplifier_service_sdk import Message

        msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        assert isinstance(msg.content, list)

    def test_json_roundtrip(self):
        from amplifier_service_sdk import Message, ToolCall

        tc = ToolCall(id="c1", name="search", arguments={"q": "test"})
        original = Message(
            role="assistant",
            content="Some response",
            tool_calls=[tc],
            tool_call_id=None,
            name="assistant",
            metadata={"ts": 123},
        )
        dumped = json.loads(original.model_dump_json())
        recovered = Message.model_validate(dumped)
        assert recovered.role == original.role
        assert recovered.content == original.content
        assert recovered.tool_calls is not None
        assert len(recovered.tool_calls) == 1
        assert recovered.tool_calls[0].name == "search"
        assert recovered.metadata == {"ts": 123}


class TestChatRequest:
    def test_minimal(self):
        from amplifier_service_sdk import ChatRequest, Message

        msg = Message(role="user", content="Hi")
        req = ChatRequest(messages=[msg])
        assert len(req.messages) == 1
        assert req.tools is None
        assert req.system is None
        assert req.max_output_tokens is None
        assert req.reasoning_effort is None
        assert req.temperature is None

    def test_all_fields(self):
        from amplifier_service_sdk import ChatRequest, Message, ToolCapability

        msg = Message(role="user", content="Hi")
        tool = ToolCapability(name="search", description="Search")
        req = ChatRequest(
            messages=[msg],
            tools=[tool],
            system="You are helpful",
            max_output_tokens=512,
            reasoning_effort="high",
            temperature=0.5,
        )
        assert req.tools is not None
        assert len(req.tools) == 1
        assert req.tools[0].name == "search"
        assert req.system == "You are helpful"
        assert req.max_output_tokens == 512
        assert req.reasoning_effort == "high"
        assert req.temperature == 0.5


class TestChatResponse:
    def test_defaults(self):
        from amplifier_service_sdk import ChatResponse

        resp = ChatResponse()
        assert resp.content is None
        assert resp.tool_calls is None
        assert resp.usage is None
        assert resp.stop_reason is None

    def test_all_fields(self):
        from amplifier_service_sdk import ChatResponse, ToolCall, TokenUsage

        tc = ToolCall(id="c1", name="search")
        usage = TokenUsage(input_tokens=10, output_tokens=20)
        resp = ChatResponse(
            content="Hello",
            tool_calls=[tc],
            usage=usage,
            stop_reason="end_turn",
        )
        assert resp.content == "Hello"
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.usage is not None
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 20
        assert resp.stop_reason == "end_turn"

    def test_content_as_list(self):
        from amplifier_service_sdk import ChatResponse

        resp = ChatResponse(content=[{"type": "text", "text": "hi"}])
        assert isinstance(resp.content, list)


class TestRoutingTable:
    def test_defaults(self):
        from amplifier_service_sdk import RoutingTable

        rt = RoutingTable()
        assert rt.tools == {}
        assert rt.providers == {}
        assert rt.hooks == {}
        assert rt.context == ""

    def test_populated(self):
        from amplifier_service_sdk import RoutingTable

        rt = RoutingTable(
            tools={"search": "search-service"},
            providers={"default": "openai"},
            hooks={"tool:before": ["audit-service"]},
            context="production",
        )
        assert rt.tools == {"search": "search-service"}
        assert rt.providers == {"default": "openai"}
        assert rt.hooks == {"tool:before": ["audit-service"]}
        assert rt.context == "production"

    def test_json_roundtrip(self):
        from amplifier_service_sdk import RoutingTable

        original = RoutingTable(
            tools={"t1": "svc1"},
            providers={"p1": "openai"},
            hooks={"h1": ["svc2", "svc3"]},
            context="test",
        )
        dumped = json.loads(original.model_dump_json())
        recovered = RoutingTable.model_validate(dumped)
        assert recovered.tools == original.tools
        assert recovered.providers == original.providers
        assert recovered.hooks == original.hooks
        assert recovered.context == original.context


class TestStreamEvent:
    def test_minimal(self):
        from amplifier_service_sdk import StreamEvent

        evt = StreamEvent(session_id="sess_1", event_type="message")
        assert evt.session_id == "sess_1"
        assert evt.event_type == "message"
        assert evt.data == {}

    def test_with_data(self):
        from amplifier_service_sdk import StreamEvent

        evt = StreamEvent(
            session_id="sess_2",
            event_type="tool_call",
            data={"tool": "search", "args": {}},
        )
        assert evt.data == {"tool": "search", "args": {}}
