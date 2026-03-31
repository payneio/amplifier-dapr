"""svc-orchestrator — Amplifier orchestrator service for coordinating multi-service workflows via Dapr."""

from svc_orchestrator.dapr_client import DaprClient as DaprClient

__all__ = ["DaprClient"]
