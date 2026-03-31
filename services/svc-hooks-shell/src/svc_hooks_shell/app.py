"""FastAPI application for the shell hook service.

Provides two integration points:
- POST /hooks/shell/invoke — synchronous pre-hook endpoint
- GET  /dapr/subscribe    — async pub/sub subscription list
- POST /events/{topic}    — Dapr CloudEvents receiver
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from amplifier_service_sdk.models import DaprSubscription, HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_shell.bridge import ShellHookBridge

_PUBSUB_NAME = "amplifier"

# Events handled synchronously as pre-hooks (colon-notation)
_PRE_HOOK_EVENTS = ["tool:pre", "prompt:submit"]

# Events consumed asynchronously via Dapr pub/sub (dot-notation topics)
_ASYNC_EVENTS = [
    "tool.post",
    "session.start",
    "session.end",
    "prompt.complete",
    "context.pre_compact",
]


def create_shell_hook_app(hooks_dir: Path | str | None = None) -> FastAPI:
    """Create and configure the shell hook FastAPI application.

    Args:
        hooks_dir: Directory containing shell hook scripts.  If ``None``,
                   reads from the ``SHELL_HOOKS_DIR`` environment variable.
                   Pass an explicit path (or ``None`` to disable hooks).
    """
    if hooks_dir is None:
        raw = os.environ.get("SHELL_HOOKS_DIR")
        hooks_dir = Path(raw) if raw else None
    elif not isinstance(hooks_dir, Path):
        hooks_dir = Path(hooks_dir)

    bridge = ShellHookBridge(hooks_dir=hooks_dir)

    # Build Dapr subscription descriptors for each async topic
    subscriptions: list[DaprSubscription] = [
        DaprSubscription(pubsubname=_PUBSUB_NAME, topic=topic)
        for topic in _ASYNC_EVENTS
    ]

    # Fast lookup set for route validation
    valid_routes: set[str] = {sub.route for sub in subscriptions}

    service_config = ServiceConfig(
        name="svc-hooks-shell",
        hooks=[
            HookRegistration(
                name="shell",
                events=_PRE_HOOK_EVENTS + [e.replace(".", ":") for e in _ASYNC_EVENTS],
                priority=50,
                mode="sync",
            )
        ],
    )

    application = create_app(service_config)

    # ------------------------------------------------------------------
    # POST /hooks/shell/invoke  — synchronous pre-hook
    # ------------------------------------------------------------------

    @application.post("/hooks/shell/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await bridge.handle(event.event, event.data)
        return result.model_dump()

    # ------------------------------------------------------------------
    # GET /dapr/subscribe  — Dapr subscription manifest
    # ------------------------------------------------------------------

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return [sub.model_dump() for sub in subscriptions]

    # ------------------------------------------------------------------
    # POST /events/{topic}  — Dapr CloudEvents receiver
    # ------------------------------------------------------------------

    @application.post("/events/{topic:path}")
    async def handle_event(topic: str, envelope: dict[str, Any]) -> dict[str, Any]:
        route = f"/events/{topic}"
        if route not in valid_routes:
            raise HTTPException(status_code=404, detail=f"Unknown event route: {route}")

        # Unwrap the Dapr CloudEvents envelope
        raw_data = envelope.get("data", {})
        if isinstance(raw_data, str):
            try:
                inner_data = json.loads(raw_data)
            except json.JSONDecodeError:
                inner_data = {}
        elif isinstance(raw_data, dict):
            inner_data = raw_data
        else:
            inner_data = {}

        # Convert dot-notation topic to colon-notation event name
        event_name = topic.replace(".", ":")
        await bridge.handle(event_name, inner_data)

        return {"status": "SUCCESS"}

    return application


# Module-level app instance for uvicorn
app = create_shell_hook_app()
