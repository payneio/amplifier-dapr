"""Pydantic v2 models for ampctl agent definitions and service maps."""

from __future__ import annotations

from typing import Any, Generator

from pydantic import BaseModel, model_validator


class ServiceEntry(BaseModel):
    """A single deployable service (image-based or build-based)."""

    image: str | None = None
    build: str | dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    environment: dict[str, str] | None = None
    volumes: list[str] | None = None
    depends_on: list[str] | None = None

    @model_validator(mode="after")
    def _require_image_or_build(self) -> "ServiceEntry":
        if self.image is None and self.build is None:
            raise ValueError("ServiceEntry must have either 'image' or 'build'")
        return self

    @property
    def source_key(self) -> str:
        """Return the image URI or build path string for hashing/identification."""
        if self.image is not None:
            return self.image
        if isinstance(self.build, dict):
            return str(self.build.get("context", ""))
        return str(self.build)


class AgentDefinition(BaseModel):
    """Full definition of an Amplifier agent."""

    ref: str
    description: str | None = None
    instruction: str | None = None
    orchestrator: ServiceEntry
    context_manager: ServiceEntry
    providers: ServiceEntry
    behaviors: dict[str, ServiceEntry] = {}

    def all_service_entries(self) -> Generator[tuple[str, ServiceEntry], None, None]:
        """Yield (role_name, ServiceEntry) tuples for all services in this definition."""
        yield "orchestrator", self.orchestrator
        yield "context_manager", self.context_manager
        yield "providers", self.providers
        for name, entry in self.behaviors.items():
            yield name, entry


class AgentDefinitionFile(BaseModel):
    """Top-level wrapper matching the YAML structure: agent: <AgentDefinition>."""

    agent: AgentDefinition


class ServiceMapEntry(BaseModel):
    """Dapr app-id mapping for a deployed agent's services."""

    orchestrator: str
    context_manager: str
    providers: str
    behaviors: dict[str, str] = {}

    def all_app_ids(self) -> list[str]:
        """Return all app-id strings for this entry."""
        ids = [self.orchestrator, self.context_manager, self.providers]
        ids.extend(self.behaviors.values())
        return ids


class ServiceMap(BaseModel):
    """Mapping of agent refs to their live service app-ids."""

    agents: dict[str, ServiceMapEntry] = {}
