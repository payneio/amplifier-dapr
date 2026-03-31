"""Async logging hook: subscribes to all Amplifier events and writes JSONL logs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult


# 10 dot-notation topics (Dapr pub/sub style)
SUBSCRIBED_TOPICS: list[str] = [
    "tool.pre",
    "tool.post",
    "tool.error",
    "session.start",
    "session.end",
    "provider.request",
    "provider.response",
    "provider.error",
    "prompt.submit",
    "prompt.complete",
]


class LoggingHook:
    """Async pub/sub hook that writes structured event logs to per-session JSONL files."""

    name: str = "logging"
    events: list[str] = [t.replace(".", ":") for t in SUBSCRIBED_TOPICS]
    priority: int = 100
    mode: Literal["sync", "async"] = "async"

    def __init__(
        self,
        log_template: str = "~/.amplifier/logs/{session_id}/events.jsonl",
    ) -> None:
        self.log_template = log_template
        self.enabled = True

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Log an event to per-session JSONL file.

        Returns CONTINUE in all cases — this hook never blocks execution.
        """
        if not self.enabled:
            return HookResult(action="CONTINUE")

        session_id: str | None = data.get("session_id")
        if not session_id:
            return HookResult(action="CONTINUE")

        log_path = Path(self.log_template.format(session_id=session_id)).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "schema": "amplifier.event.v1",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "event": event,
            "data": self._sanitize_for_json(data),
        }

        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

        return HookResult(action="CONTINUE")

    def _sanitize_for_json(self, value: Any) -> Any:
        """Recursively convert a value to a JSON-safe representation."""
        if isinstance(value, dict):
            return {k: self._sanitize_for_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_for_json(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)
