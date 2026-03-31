"""Todo hook stubs — stubbed until shared state is available."""

from __future__ import annotations

from amplifier_service_sdk.models import HookEvent, HookResult


class TodoReminderHook:
    """Hook stub: reminds about pending todos. Returns CONTINUE until shared state is available."""

    name = "todo_reminder"

    async def handle(self, event: HookEvent) -> HookResult:
        """Handle hook event — stub returns CONTINUE."""
        return HookResult(action="CONTINUE")


class TodoDisplayHook:
    """Hook stub: displays todo state in UI. Returns CONTINUE until shared state is available."""

    name = "todo_display"

    async def handle(self, event: HookEvent) -> HookResult:
        """Handle hook event — stub returns CONTINUE."""
        return HookResult(action="CONTINUE")
