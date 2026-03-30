"""Tests for Pydantic v2 models in amplifier_service_sdk."""

import json

from amplifier_service_sdk import (
    ContentFile,
    DescribeResponse,
    HealthResponse,
    HookEvent,
    HookResult,
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


class TestDescribeResponse:
    def test_minimal(self):
        resp = DescribeResponse(name="my-service")
        assert resp.name == "my-service"
        assert resp.version == "0.1.0"
        assert resp.tools == []
        assert resp.hooks == []
        assert resp.providers == []
        assert resp.content_paths == []

    def test_with_tools(self):
        tool = ToolCapability(name="do_thing", description="Does the thing")
        resp = DescribeResponse(name="my-service", tools=[tool])
        assert len(resp.tools) == 1
        assert resp.tools[0].name == "do_thing"

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
        assert len(resp.tool_calls) == 1
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
