"""FastAPI application for the async pub/sub hooks service."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException

from amplifier_service_sdk.models import DaprSubscription, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_async.logging_hook import SUBSCRIBED_TOPICS, LoggingHook

_PUBSUB_NAME = "amplifier"


def create_async_hooks_app(log_template: str | None = None) -> FastAPI:
    """Create and configure the async hooks FastAPI application.

    Args:
        log_template: Path template for JSONL log files, with ``{session_id}``
                      placeholder.  If ``None``, reads from the ``LOG_TEMPLATE``
                      environment variable, or uses the default template.
    """
    if log_template is None:
        log_template = os.environ.get("LOG_TEMPLATE") or None

    logging_hook = (
        LoggingHook(log_template=log_template) if log_template else LoggingHook()
    )

    # Build Dapr subscription list for all subscribed topics (dot-notation)
    subscriptions: list[DaprSubscription] = [
        DaprSubscription(pubsubname=_PUBSUB_NAME, topic=topic)
        for topic in SUBSCRIBED_TOPICS
    ]

    # Build a set of valid routes for fast 404 detection
    valid_routes: set[str] = {sub.route for sub in subscriptions}

    service_config = ServiceConfig(
        name="svc-hooks-async",
        hooks=[
            HookRegistration(
                name=LoggingHook.name,
                events=LoggingHook.events,
                priority=LoggingHook.priority,
                mode=LoggingHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return [sub.model_dump() for sub in subscriptions]

    @application.post("/events/{topic:path}")
    async def handle_event(topic: str, envelope: dict[str, Any]) -> dict[str, Any]:
        route = f"/events/{topic}"
        if route not in valid_routes:
            raise HTTPException(status_code=404, detail=f"Unknown event route: {route}")

        # Extract inner data from the Dapr CloudEvents envelope
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

        # Map dot-notation topic to colon-notation event name
        event = topic.replace(".", ":")

        await logging_hook.handle(event, inner_data)

        return {"status": "SUCCESS"}

    return application


# Module-level app instance for uvicorn
app = create_async_hooks_app()
