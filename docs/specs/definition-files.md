# Definition Files Spec

Definition files are YAML files that declare agents and behaviors in the Amplifier IPC system. An **agent** is the top-level unit of composition -- it names which services to include and how they are configured. A **behavior** is a unit of capability (tools, hooks, context) backed by one or more microservices. Agents compose behaviors; behaviors can compose other behaviors recursively.

This document is the authoritative reference for definition file formats, service composition, and configuration.

---

## Architecture Context

In the Dapr-native microservices architecture, definitions serve a different role than in the old stdio/subprocess system:

- **Behavior YAMLs** declare which services to compose for a given capability. Each behavior maps to one or more `svc-*` containers.
- **Agent definitions** compose behaviors into a complete agent by listing the behaviors to include.
- **The session-service** resolves definitions at session startup, builds routing tables that map tool/hook/provider names to Dapr service endpoints, and orchestrates the session lifecycle.

There is no `definitions/` cache directory, no `scan_package()` discovery, and no spawn-describe-configure lifecycle. Services are running containers discovered via Dapr service invocation.

---

## Agent Definition Schema

An agent definition uses `agent:` as the top-level YAML key.

```yaml
agent:
  ref: amplifier-dev
  uuid: 52d19e87-24ba-4291-a872-69d963b96ce9
  version: 1
  description: Amplifier development agent with full foundation capabilities

  provider: anthropic

  tools: true
  hooks: true
  agents: true
  context: true

  behaviors:
    - modes
    - skills
    - routing
```

### Agent-only fields

- **`provider`** -- Names the LLM provider the orchestrator should use (resolved to `svc-providers` or `svc-mock-provider` via Dapr).
- **`agents`** -- Boolean. Whether this agent contributes sub-agent (delegation) capabilities.

---

## Behavior Definition Schema

A behavior definition uses `behavior:` as the top-level YAML key.

```yaml
behavior:
  ref: modes
  uuid: 6d239fcc-e53b-4a6d-a81c-3b3a5a8fc139
  version: 1
  description: Generic mode system for runtime behavior modification

  tools: true
  hooks: true
  context: true

  services:
    - svc-modes
```

Behaviors declare which `svc-*` services they require in the `services:` list. The session-service uses this to build the routing table -- mapping tool names, hook events, and provider names to their container endpoints.

Behaviors may compose other behaviors by listing them in `behaviors:`, using the same format as agents. This is recursive.

Content-only behaviors that provide only context documents list `svc-content-*` services and have no runtime tools or hooks.

---

## Service Composition

### How definitions map to containers

Each `svc-*` directory under `services/` is an independent Docker container in the `docker-compose.yaml`. Definitions don't spawn processes -- they declare which already-running containers to route to.

```
Agent definition
  -> lists behaviors
    -> each behavior lists svc-* services
      -> session-service builds routing table
        -> orchestrator uses routing table for Dapr service invocation
```

### Routing table construction

At session startup, the session-service:

1. Resolves the agent definition and all composed behaviors
2. Collects all referenced `svc-*` services
3. Queries each service's `GET /describe` endpoint for its capabilities (tools, hooks, content)
4. Builds a routing table: `{tool_name -> svc-name, hook_event -> [svc-name], provider_name -> svc-name}`
5. Passes the routing table to the orchestrator

The orchestrator then uses Dapr service invocation to dispatch calls to the correct container.

---

## Identity and Namespacing

### Definition identity

Every definition (agent or behavior) has two identity fields:

- **`ref`** -- A short, human-readable name (e.g., `modes`, `amplifier-dev`).
- **`uuid`** -- A globally unique identifier (UUID v4).

### Behavior aliasing

When an agent composes behaviors, each behavior entry is an alias. Alias uniqueness is enforced within a single agent's resolved tree.

---

## Component Configuration

The `config:` block declares configuration for service components. Keys are component names, optionally prefixed with `<ref>:` to target included behaviors' components.

### Behavior-level config

```yaml
behavior:
  ref: modes
  tools: true
  hooks: true
  config:
    mode-tool:
      gate_policy: warn
```

A behavior's `config:` block sets default values for its services' components.

### Agent-level config (overrides)

```yaml
agent:
  ref: amplifier-dev
  behaviors:
    - modes

  config:
    modes:mode-tool:
      gate_policy: block
```

An agent's `config:` block can override config from included behaviors. Use the `<ref>:<component_name>` syntax to target a specific behavior's component.

### Resolution order

Outer definitions override inner definitions:

1. **Agent `config:`** (highest priority)
2. **Behavior `config:`** (defaults)
3. **Service defaults** (hardcoded in the service)

### Config delivery to services

Configuration is delivered to services at session startup via the session-service. The session-service merges config from the agent and behavior definitions, then passes it to each service as query parameters or headers on Dapr service invocation calls. Services receive their resolved config and apply it.

All config is static -- set once at session startup, not changed per-call.

---

## Field Reference

### All fields

| Field | Type | Required | Agent | Behavior | Description |
|---|---|---|---|---|---|
| `ref` | string | **yes** | yes | yes | Short human-readable name |
| `uuid` | UUID v4 | **yes** | yes | yes | Globally unique identifier |
| `version` | int | no | yes | yes | Definition version number |
| `description` | string | no | yes | yes | Human-readable description |
| `provider` | string | no | yes | no | LLM provider name (resolved via Dapr to svc-providers) |
| `tools` | bool | no | yes | yes | Contributes tools from composed services |
| `hooks` | bool | no | yes | yes | Contributes hooks from composed services |
| `agents` | bool | no | yes | no | Contributes sub-agent (delegation) capabilities |
| `context` | bool | no | yes | yes | Contributes context from composed services |
| `behaviors` | list | no | yes | yes | Composed behaviors |
| `config` | object | no | yes | yes | Per-component configuration |
| `services` | list of strings | no | yes | yes | List of svc-* service names to include |

### Top-level key

| Key | Meaning |
|---|---|
| `agent:` | This file defines an agent |
| `behavior:` | This file defines a behavior |
