"""Tests for Phase 3b models: HookRegistration, DaprSubscription, RoutingTable extensions."""

import json

import pytest

from amplifier_service_sdk.models import (
    DaprSubscription,
    DescribeResponse,
    HookRegistration,
    RoutingTable,
)


class TestDaprSubscription:
    def test_required_fields(self):
        sub = DaprSubscription(pubsubname="my-pubsub", topic="my-topic")
        assert sub.pubsubname == "my-pubsub"
        assert sub.topic == "my-topic"

    def test_route_default_set_from_topic(self):
        """route defaults to /events/{topic} after model_post_init."""
        sub = DaprSubscription(pubsubname="ps", topic="my-topic")
        assert sub.route == "/events/my-topic"

    def test_route_colons_replaced_with_dots(self):
        """Colons in topic are replaced with dots in the route."""
        sub = DaprSubscription(pubsubname="ps", topic="amplifier:session:started")
        assert sub.route == "/events/amplifier.session.started"

    def test_route_explicit_override(self):
        """Explicit route is preserved (not overwritten by model_post_init)."""
        sub = DaprSubscription(pubsubname="ps", topic="my-topic", route="/custom/path")
        assert sub.route == "/custom/path"

    def test_json_roundtrip(self):
        sub = DaprSubscription(pubsubname="ps", topic="foo:bar")
        data = json.loads(sub.model_dump_json())
        recovered = DaprSubscription.model_validate(data)
        assert recovered.pubsubname == sub.pubsubname
        assert recovered.topic == sub.topic
        assert recovered.route == sub.route


class TestHookRegistration:
    def test_required_name_field(self):
        reg = HookRegistration(name="my-hook")
        assert reg.name == "my-hook"

    def test_events_default_empty_list(self):
        reg = HookRegistration(name="my-hook")
        assert reg.events == []

    def test_priority_defaults_to_50(self):
        reg = HookRegistration(name="my-hook")
        assert reg.priority == 50

    def test_mode_defaults_to_sync(self):
        reg = HookRegistration(name="my-hook")
        assert reg.mode == "sync"

    def test_explicit_events(self):
        reg = HookRegistration(name="my-hook", events=["tool.before", "tool.after"])
        assert reg.events == ["tool.before", "tool.after"]

    def test_explicit_priority(self):
        reg = HookRegistration(name="my-hook", priority=10)
        assert reg.priority == 10

    def test_async_mode(self):
        reg = HookRegistration(name="my-hook", mode="async")
        assert reg.mode == "async"

    def test_json_roundtrip(self):
        reg = HookRegistration(name="test", events=["e1"], priority=30, mode="async")
        data = json.loads(reg.model_dump_json())
        recovered = HookRegistration.model_validate(data)
        assert recovered.name == reg.name
        assert recovered.events == reg.events
        assert recovered.priority == reg.priority
        assert recovered.mode == reg.mode


class TestRoutingTableExtensions:
    def test_hook_endpoints_defaults_empty(self):
        rt = RoutingTable()
        assert rt.hook_endpoints == {}

    def test_hook_priorities_defaults_empty(self):
        rt = RoutingTable()
        assert rt.hook_priorities == {}

    def test_hook_endpoints_roundtrip(self):
        rt = RoutingTable(hook_endpoints={"svc-hooks": "/hooks/invoke"})
        assert rt.hook_endpoints == {"svc-hooks": "/hooks/invoke"}
        data = json.loads(rt.model_dump_json())
        recovered = RoutingTable.model_validate(data)
        assert recovered.hook_endpoints == {"svc-hooks": "/hooks/invoke"}

    def test_hook_priorities_roundtrip(self):
        rt = RoutingTable(hook_priorities={"svc-hooks": 10})
        assert rt.hook_priorities == {"svc-hooks": 10}
        data = json.loads(rt.model_dump_json())
        recovered = RoutingTable.model_validate(data)
        assert recovered.hook_priorities == {"svc-hooks": 10}

    def test_existing_fields_unaffected(self):
        """Ensure original RoutingTable fields still work."""
        rt = RoutingTable(
            tools={"my-tool": "svc-tools"},
            providers={"openai": "svc-providers"},
            hooks={"pre_tool": ["svc-hooks"]},
            context="some-context",
        )
        assert rt.tools == {"my-tool": "svc-tools"}
        assert rt.providers == {"openai": "svc-providers"}
        assert rt.hooks == {"pre_tool": ["svc-hooks"]}
        assert rt.context == "some-context"


class TestDescribeResponseHooksField:
    def test_hooks_accepts_hook_registration_list(self):
        """DescribeResponse.hooks should accept list[HookRegistration]."""
        reg = HookRegistration(name="pre-tool", events=["tool.before"], priority=10)
        resp = DescribeResponse(name="my-service", hooks=[reg])
        assert len(resp.hooks) == 1
        assert resp.hooks[0].name == "pre-tool"
        assert resp.hooks[0].priority == 10

    def test_hooks_defaults_empty(self):
        resp = DescribeResponse(name="my-service")
        assert resp.hooks == []

    def test_hooks_roundtrip(self):
        reg = HookRegistration(name="pre-tool", events=["tool.before"])
        resp = DescribeResponse(name="my-service", hooks=[reg])
        data = json.loads(resp.model_dump_json())
        recovered = DescribeResponse.model_validate(data)
        assert len(recovered.hooks) == 1
        assert isinstance(recovered.hooks[0], HookRegistration)
        assert recovered.hooks[0].name == "pre-tool"
