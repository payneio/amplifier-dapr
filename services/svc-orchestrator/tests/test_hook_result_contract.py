"""Tests for HookResult top-level field contract (context_injection, context_injection_role, ephemeral)."""

from __future__ import annotations

from amplifier_service_sdk.models import HookResult


class TestHookResultContract:
    """Verify HookResult exposes context_injection, context_injection_role, ephemeral as top-level fields."""

    def test_context_injection_field_exists(self) -> None:
        """HookResult accepts context_injection and ephemeral as top-level kwargs."""
        result = HookResult(
            action="INJECT_CONTEXT",
            context_injection="You must remember this.",
            ephemeral=True,
        )
        assert result.context_injection == "You must remember this."
        assert result.ephemeral is True

    def test_context_injection_role_defaults_to_system(self) -> None:
        """context_injection_role defaults to 'system'."""
        result = HookResult(action="INJECT_CONTEXT", context_injection="hello")
        assert result.context_injection_role == "system"

    def test_ephemeral_defaults_to_false(self) -> None:
        """ephemeral defaults to False."""
        result = HookResult(action="CONTINUE")
        assert result.ephemeral is False

    def test_context_injection_defaults_to_none(self) -> None:
        """context_injection defaults to None."""
        result = HookResult(action="CONTINUE")
        assert result.context_injection is None

    def test_backward_compat_data_dict_still_works(self) -> None:
        """HookResult still accepts old data dict format for backward compatibility."""
        result = HookResult(
            action="INJECT_CONTEXT",
            data={"context_injection": "legacy", "ephemeral": True},
        )
        assert result.data is not None
        assert result.data["context_injection"] == "legacy"
        assert result.data["ephemeral"] is True
        # action still set correctly
        assert result.action == "INJECT_CONTEXT"
