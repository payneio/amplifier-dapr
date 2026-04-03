"""Tests for RedactionHook — secrets scanning and redaction."""

import pytest
from svc_hooks_redaction.hook import RedactionHook


@pytest.fixture
def hook():
    return RedactionHook()


class TestRedactionPatterns:
    """Covers individual secret pattern detection and redaction."""

    async def test_aws_key_redacted(self, hook):
        data = {"content": "My AWS key is AKIAIOSFODNN7EXAMPLE1234"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert "[REDACTED:aws-key]" in result.data["content"]
        assert "AKIA" not in result.data["content"]

    async def test_jwt_redacted(self, hook):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.abc123signature"
        data = {"token": jwt}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert "[REDACTED:jwt]" in result.data["token"]
        assert "eyJ" not in result.data["token"]

    async def test_api_key_redacted(self, hook):
        data = {"key": "sk-abcdefghijklmnopqrstuvwxyz1234567890"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert "[REDACTED:api-key]" in result.data["key"]
        assert "sk-" not in result.data["key"]

    async def test_email_redacted(self, hook):
        data = {"user": "Contact me at user@example.com for details"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert "[REDACTED:email]" in result.data["user"]
        assert "user@example.com" not in result.data["user"]

    async def test_private_key_redacted(self, hook):
        data = {
            "pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ\n-----END RSA PRIVATE KEY-----"
        }
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert "[REDACTED:private-key]" in result.data["pem"]
        assert "BEGIN RSA PRIVATE KEY" not in result.data["pem"]

    async def test_no_secrets_returns_continue(self, hook):
        data = {"content": "Hello, world! No secrets here.", "count": 42}
        result = await hook.handle("tool:pre", data)
        assert result.action == "CONTINUE"


class TestStructuralFieldSkipping:
    """Structural fields must be preserved as-is even if they look like secrets."""

    async def test_tool_name_preserved(self, hook):
        # tool_name is a structural field — should not be scanned
        # Use a value that genuinely matches the api-key pattern (sk- + 20 alphanumerics)
        data = {
            "tool_name": "sk-abcdefghijklmnopqrstu",
            "content": "safe content",
        }
        result = await hook.handle("tool:pre", data)
        # tool_name should be untouched; no redaction in structural field
        assert result.action == "CONTINUE"
        # Verify the field itself would match the pattern if processed
        # (meaning the test is valid — it really would match without the skip)
        import re

        assert re.search(r"sk-[a-zA-Z0-9]{20,}", data["tool_name"])

    async def test_event_field_preserved(self, hook):
        # event is a structural field — should not be scanned
        data = {
            "event": "tool:pre",
            "content": "nothing sensitive",
        }
        result = await hook.handle("tool:pre", data)
        assert result.action == "CONTINUE"


class TestNestedRedaction:
    """Verifies recursive processing of nested data structures."""

    async def test_nested_dict_values_redacted(self, hook):
        # Use exactly 20-char AWS key (AKIA + 16 uppercase alphanumerics) so the
        # entire string is replaced without any trailing characters.
        data = {
            "outer": {
                "inner": {
                    "secret": "AKIAIOSFODNN7EXAMPLE",
                }
            }
        }
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert result.data["outer"]["inner"]["secret"] == "[REDACTED:aws-key]"

    async def test_list_items_redacted(self, hook):
        data = {
            "messages": [
                {"role": "user", "content": "my key: AKIAIOSFODNN7EXAMPLE1234"},
                {"role": "assistant", "content": "noted"},
            ]
        }
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert result.data is not None
        assert "[REDACTED:aws-key]" in result.data["messages"][0]["content"]
        assert result.data["messages"][1]["content"] == "noted"


class TestUnrelatedEvents:
    """RedactionHook fires on ALL event types."""

    async def test_all_event_types_fire_redaction(self, hook):
        secret_data = {"content": "AKIAIOSFODNN7EXAMPLE1234"}
        for event_type in [
            "tool:pre",
            "tool:post",
            "provider:request",
            "session:start",
        ]:
            result = await hook.handle(event_type, secret_data)
            assert result.action == "MODIFY", (
                f"Expected MODIFY for event {event_type!r}"
            )
            assert result.data is not None
            assert "[REDACTED:aws-key]" in result.data["content"]
