# Amplifier Specification

> **Status:** Authoritative source-of-truth for the amplifier architecture.
> This document supersedes all prior specs and design documents.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Service Contract](#3-service-contract)
4. [Machine Service](#4-machine-service)
5. [Communication Patterns](#5-communication-patterns)
6. [Session Lifecycle](#6-session-lifecycle)
7. [Deployment](#7-deployment)
8. [SDK](#8-sdk)
9. [Service Inventory](#9-service-inventory)
10. [CLI](#10-cli)
11. [Data Models](#11-data-models)
12. [Error Handling](#12-error-handling)
13. [Testing Strategy](#13-testing-strategy)
14. [Open Questions](#14-open-questions)

---

## 1. Overview

Amplifier is a **Dapr-native microservices framework** for AI agent orchestration. Every behavior runs as an independent container communicating via **HTTP and Dapr service invocation/pub/sub**. A Session Service acts as the gateway, an Orchestrator drives the agent loop, and capability services (tools, providers, hooks) expose standard HTTP endpoints. Redis backs state storage and pub/sub messaging. Dapr sidecars provide mTLS, retries, circuit breakers, and observability for every container.

### Goals

- **Container-per-behavior** -- each tool, hook, or provider group runs in its own container with full dependency isolation
- **Standard HTTP endpoints** -- no custom wire protocol; services are ordinary HTTP servers with well-known paths
- **Dapr service mesh** -- service invocation, pub/sub, state store, and health monitoring out of the box
- **Language-agnostic** -- any language that can serve HTTP can implement a service (Python, Go, Rust, TypeScript)
- **Machine abstraction** -- a dedicated Machine Service centralizes filesystem and command access, bridging the container isolation boundary
- **Composable agents and behaviors** -- behavior YAML definitions compose capabilities from independent services

### What Changed

Amplifier replaced the prior architecture's:
- **stdio JSON-RPC transport** with HTTP + Dapr service invocation and pub/sub
- **Per-turn process spawning** with long-lived containers
- **Host monolith** (1248-line message broker) with a thin Session Service for lifecycle only
- **Custom Server/Client classes** with standard HTTP frameworks (FastAPI)
- **`_OrchestratorLocalClient` co-location hack** with true service isolation -- the orchestrator calls tools/providers via Dapr
- **In-process `scan_package()` discovery** with HTTP `GET /describe` endpoints
- **`state.json` file persistence** with Dapr state store (Redis)

---

## 2. Architecture

### System Overview

```
+---------------------------------------------------------------------+
|  User's Machine                                                     |
|  +----------+                                                       |
|  |   CLI    |---- HTTP ----+                                        |
|  +----------+              |                                        |
|       ^                    |                                        |
|       | pub/sub streaming  |                                        |
|       | (tokens + events)  |                                        |
+-------+--------------------+----------------------------------------+
        |                    v
+-------+------------------------------------------------------------+
|  Docker Compose            |                                        |
|                  +---------v---------+                               |
|                  |  Session Service  |                               |
|                  | (lifecycle only)  |                               |
|                  +---------+---------+                               |
|                            |                                        |
|                  +---------v---------+                               |
|                  |   Orchestrator    |                               |
|                  | (agent loop)      |                               |
|                  +--+------+------+--+                               |
|                     |      |      |                                  |
|              +------+  +---+---+  +------+                           |
|              |Provid|  | Tools |  | Hooks|                           |
|              |(Dapr)|  |(Dapr) |  |(p/s) |                           |
|              +------+  +---+---+  +------+                           |
|                            |                                        |
|                  +---------v---------+                               |
|                  |  Machine Service  |                               |
|                  | (fs + exec)       |                               |
|                  | [volume mounted]  |                               |
|                  +-------------------+                               |
|                                                                     |
|     +-------+ Content Services (/describe + /content only) +------+ |
|                                                                     |
|     +---------+                                                     |
|     |  Redis  |  (Dapr state store + pub/sub broker)                |
|     +---------+                                                     |
|                                                                     |
|  Every container has a Dapr sidecar (mTLS, retries, observability)  |
+---------------------------------------------------------------------+
```

### Component Roles

**CLI** -- Runs on the user's machine (not a container). Resolves workspace content (`@mentions`, `.amplifier/` files, `AGENTS.md`), sends resolved content + prompt as an HTTP payload to the Session Service. Subscribes to a pub/sub streaming topic for real-time tokens and events.

**Session Service** -- Containerized gateway for session lifecycle. Receives prompts with resolved content, resolves agent/behavior definitions, calls `GET /describe` on active services to build the routing table and collect content manifests, assembles the system prompt from service content + workspace content, invokes the orchestrator via Dapr service invocation, persists transcripts via Dapr state store, and streams events back to the CLI. Not in the hot path for tool/provider/hook calls.

**Orchestrator Service** -- Drives the agent loop. Receives the routing table as input (which tool lives at which Dapr app-id). Calls providers, tools, and pre-hooks directly via Dapr service invocation. Publishes post-hook events and streaming tokens via pub/sub. Does not route through the Session Service for runtime messages.

**Capability Services** -- Provider, tool, hook, mode, skills, etc. containers. Each exposes well-known HTTP endpoints following the service contract. Split by behavior -- each behavior becomes its own container.

**Machine Service** -- Centralizes all filesystem and command execution access behind a single Dapr service. Tool services call it via Dapr service invocation for all filesystem and command operations instead of touching the filesystem directly.

**Content Services** -- Containers that serve only `/describe` and `/content/{path}` with no capability endpoints. They carry context documentation, agent definitions, and recipes.

**Redis** -- Dapr state store for session persistence and pub/sub broker for streaming and hook events.

**Dapr Sidecars** -- Every container gets a sidecar providing service invocation (mTLS, retries, circuit breakers), pub/sub, state store access, and observability.

### Orchestrator Drives All Logic

The orchestrator keeps its full loop logic:
- Calls pre-hooks via sequential service invocation (may DENY or MODIFY)
- Calls providers via service invocation
- Dispatches tool calls via service invocation
- Publishes post-hook events via pub/sub
- Publishes streaming tokens via pub/sub
- Signals completion when the agent loop finishes

The key difference: the orchestrator receives the routing table as input from the Session Service rather than discovering it at runtime. It calls tools and providers directly via Dapr, not through the Session Service.

---

## 3. Service Contract

There is **one kind of service**. Every service:

1. Has a Dapr app-id
2. Responds to `GET /describe` with its capability + content manifest
3. Serves content via `GET /content/{path}`
4. Responds to `GET /healthz` for Dapr health monitoring
5. Optionally exposes tool, provider, and/or hook endpoints
6. Optionally subscribes to pub/sub topics (hooks)

The variation is in what capabilities a service offers, not in what "type" it is.

### Universal Endpoints

Every service exposes these:

| Endpoint | Method | Description |
|---|---|---|
| `/describe` | GET | Returns capability manifest (tools, providers, hooks) + content manifest (file paths) |
| `/content/{path}` | GET | Serves content files (context docs, agent definitions, recipes) on demand |
| `/healthz` | GET | Dapr-standard health check |

### Capability Endpoints

Services expose these based on what they offer:

| Component Type | Endpoint | Method | Description |
|---|---|---|---|
| Tool | `/tools/{name}/execute` | POST | Takes tool input, returns tool result |
| Provider | `/providers/{name}/complete` | POST | Takes a chat request, returns completion |
| Provider | `/providers/{name}/stream` | POST | Publishes tokens to session's pub/sub topic |
| Pre-Hook | `/hooks/{name}/invoke` | POST | Called via service invocation; may modify or block the request |
| Post-Hook | *(none -- subscribes to pub/sub topics)* | -- | Subscribes to event topics declaratively |
| Orchestrator | `/orchestrator/execute` | POST | Accepts session config + prompt, drives the loop, returns final result |

### Describe Response

The `GET /describe` response provides the capability and content manifest:

```json
{
  "name": "svc-machine",
  "capabilities": {
    "tools": [
      {"name": "bash", "description": "...", "input_schema": {}},
      {"name": "read_file", "description": "...", "input_schema": {}},
      {"name": "write_file", "description": "...", "input_schema": {}},
      {"name": "edit_file", "description": "...", "input_schema": {}},
      {"name": "grep", "description": "...", "input_schema": {}},
      {"name": "glob", "description": "...", "input_schema": {}}
    ],
    "providers": [],
    "hooks": []
  },
  "content": {
    "paths": ["context/filesystem-instructions.md"]
  }
}
```

### Hook Execution Model

Hooks are split into two categories based on timing:

| Hook Timing | Pattern | Reason |
|---|---|---|
| `*:pre` events | Service invocation (sequential) | May modify or block the request (DENY, MODIFY) |
| `*:post` events | Pub/sub (parallel) | Observation only, fire-and-forget |

Pre-hooks are called sequentially via Dapr service invocation. The orchestrator calls each pre-hook's `/hooks/{name}/invoke` endpoint and inspects the result. A DENY action stops the chain. A MODIFY action updates the data for subsequent hooks.

Post-hooks subscribe to pub/sub topics declaratively. The orchestrator publishes the event and moves on without waiting. Post-hooks process events asynchronously.

### Hook Events

Standard lifecycle events:

| Event | Fired When |
|---|---|
| `prompt:submit` | User prompt received, before processing |
| `prompt:complete` | Full response ready to return |
| `provider:request` | Before sending request to LLM provider |
| `provider:error` | Provider returns an error |
| `tool:pre` | Before executing a tool call |
| `tool:post` | After tool execution completes |
| `tool:error` | Tool execution fails |
| `orchestrator:complete` | Orchestrator loop finishes |
| `content_block:start` | Streaming content block begins |
| `content_block:end` | Streaming content block ends |

---

## 4. Machine Service

### The Problem

In a containerized world, each tool service is isolated with no access to the user's workspace. Tools like bash, filesystem, grep, and glob all need to read/write the user's project directory and execute shell commands. Without a central access point, each tool container would need its own volume mount and subprocess logic.

### The Solution

The Machine Service centralizes all workspace interactions behind a single Dapr service. Tool services call it via Dapr service invocation for all filesystem and command operations.

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/exec` | POST | Execute shell command. Returns stdout, stderr, exit code. |
| `/files/read` | POST | Read file contents (path, offset, limit) |
| `/files/write` | POST | Write file contents |
| `/files/edit` | POST | Edit file (string replacement) |
| `/files/list` | POST | List directory contents |
| `/files/glob` | POST | Glob pattern matching |
| `/files/grep` | POST | Search file contents with regex |

### Two Modes

The Machine Service exposes the same HTTP endpoints regardless of mode. Tool services never know which backend is active.

**Local mode (current):** The user's workspace directory is volume-mounted into the Machine Service container. Commands execute via `asyncio.create_subprocess_exec()`. File operations use standard filesystem calls. All paths are sandboxed within the mounted workspace directory (path traversal is blocked).

```yaml
# docker-compose.yaml
svc-machine:
  volumes:
    - ${WORKSPACE_PATH:-.}:/workspace
  environment:
    - MACHINE_WORKSPACE_DIR=/workspace
```

**Remote mode (future):** The same endpoints proxy to a remote host via SSH (for commands) and SFTP (for file operations). Enables cloud-hosted dev environments, remote GPU machines, or shared team workspaces.

### How Tools Use It

Tools call the Machine Service via Dapr service invocation instead of executing directly:

```python
# Tool calls Machine Service for shell execution
result = await dapr_client.invoke_method(
    app_id="svc-machine",
    method_name="exec",
    data=json.dumps({"command": command, "timeout": 30, "working_dir": "/workspace"})
)

# Tool calls Machine Service for file reads
content = await dapr_client.invoke_method(
    app_id="svc-machine",
    method_name="files/read",
    data=json.dumps({"path": file_path})
)
```

---

## 5. Communication Patterns

Three communication patterns cover all interactions in the system.

### Pattern 1: Service Invocation (Request/Response)

**Used for:** tool execution, provider completion, `/describe`, `/content/{path}`, pre-hooks, Machine Service calls

The caller invokes a specific service endpoint and waits for the result. Dapr service invocation provides mTLS, retries, and circuit breakers automatically.

```
Orchestrator --[Dapr SI]--> svc-machine /tools/bash/execute
Orchestrator --[Dapr SI]--> svc-providers /providers/anthropic/complete
Orchestrator --[Dapr SI]--> svc-modes /hooks/mode/invoke
Session Svc  --[Dapr SI]--> any-service /describe
```

### Pattern 2: Pub/Sub Streaming Subscriptions (Token Streaming)

**Used for:** streaming LLM tokens from provider through orchestrator to CLI

The orchestrator publishes tokens to a session-scoped topic as they arrive from the provider. The CLI subscribes via Dapr streaming subscriptions (pull-based message delivery over gRPC, available since Dapr v1.14) and renders in real-time.

```
Provider --> Orchestrator --[pub/sub]--> session.{id}.stream --> CLI
```

Stream event types:

| Event | Payload | Meaning |
|---|---|---|
| `stream.token` | `{text}` | Text chunk from LLM |
| `stream.thinking` | `{text}` | Thinking/reasoning text |
| `stream.tool_call_start` | `{name, id}` | Tool call beginning |
| `stream.content_block_start` | `{type, index}` | Streaming content block begins |
| `stream.content_block_end` | `{type, index}` | Streaming content block ends |
| `complete` | `{response}` | Turn finished |

### Pattern 3: Pub/Sub Declarative Subscriptions (Post-Hooks)

**Used for:** post-hook lifecycle events (`tool:post`, `prompt:complete`, `orchestrator:complete`, etc.)

The orchestrator publishes hook events to a topic. Hook services subscribe declaratively via Dapr subscription configuration. Events are delivered in parallel to all subscribers. This replaces the prior sequential host-mediated fan-out.

```
Orchestrator --[pub/sub]--> hooks.tool.post --> svc-logging, svc-progress-monitor
Orchestrator --[pub/sub]--> hooks.prompt.complete --> svc-sessions, svc-status-context
```

---

## 6. Session Lifecycle

A session turn proceeds in three phases.

### Phase 1: Setup (CLI + Session Service)

1. User types prompt in CLI
2. CLI resolves local workspace content (`.amplifier/AGENTS.md`, settings, workspace `@mentions`)
3. CLI sends HTTP request to Session Service: `POST /sessions/{id}/turn` with prompt, workspace_content, agent_ref
4. Session Service resolves agent definition --> determines active behaviors --> determines needed services
5. Session Service calls `GET /describe` on each needed service --> builds capability routing table + collects content manifests
6. Session Service calls `GET /content/{path}` on services for needed context files
7. Session Service assembles full system prompt: service content + workspace content + conversation history

### Phase 2: Agent Loop (Orchestrator Drives)

8. Session Service invokes orchestrator: `POST /orchestrator/execute` with system_prompt, messages, config, routing_table
9. Orchestrator enters the agent loop:
   - a. Calls pre-hooks via service invocation (sequential, may DENY or MODIFY)
   - b. Calls provider via service invocation
   - c. Provider tokens published to pub/sub topic --> CLI renders in real-time
   - d. On tool call: calls tool pre-hooks, executes tool via service invocation, publishes tool post-hook events
   - e. Repeats until LLM signals completion
10. Orchestrator publishes completion event

### Phase 3: Teardown

11. Session Service receives completion
12. Persists transcript to Dapr state store (Redis)
13. Returns final result to CLI

**Key design point:** The routing table is computed once during setup and passed to the orchestrator as input. The orchestrator does not discover services -- it receives a map of `tool_name --> dapr_app_id` and calls services directly. The Session Service is not in the hot path during the agent loop.

---

## 7. Deployment

### Container Inventory

All services share a base image. The `amplifier-foundation` monolith is split by behavior -- each behavior becomes its own container.

#### From amplifier-foundation (Split by Behavior)

| Container | From Behavior | Components |
|---|---|---|
| `svc-orchestrator` | (core) | StreamingOrchestrator + SimpleContextManager |
| `svc-delegate` | agents | DelegateTool |
| `svc-task` | tasks | TaskTool |
| `svc-todo` | todo-reminder | TodoTool + TodoReminderHook + TodoDisplayHook |
| `svc-web` | (tool) | WebSearchTool, WebFetchTool |
| `svc-logging` | logging | LoggingHook |
| `svc-redaction` | redaction | RedactionHook |
| `svc-sessions` | sessions | SessionNamingHook + content |
| `svc-status-context` | status-context | StatusContextHook |
| `svc-progress-monitor` | progress-monitor | ProgressMonitorHook |
| `svc-streaming-ui` | streaming-ui | StreamingUiHook |

#### Already-Separate Services

| Container | Components |
|---|---|
| `svc-providers` | 8 LLM providers (anthropic, openai, azure_openai, gemini, ollama, vllm, github_copilot, mock) |
| `svc-modes` | ModeTool + ModeHook |
| `svc-routing` | RoutingHook + routing matrix data |
| `svc-skills` | SkillsTool |

#### Content Services (Serve /describe + /content Only)

| Container |
|---|
| `svc-core` |
| `svc-amplifier` |
| `svc-browser-tester` |
| `svc-design-intelligence` |
| `svc-filesystem-content` |
| `svc-recipes` |
| `svc-superpowers` |
| `svc-system-design-intelligence` |

#### Infrastructure

| Container | Role |
|---|---|
| `svc-machine` | Consolidated machine service: bash, read_file, write_file, edit_file, grep, glob. Per-session instances via SSH/SFTP driver. |
| `session-service` | Session lifecycle gateway |
| `redis` | Dapr state store + pub/sub broker |

**Total: ~26 application containers + Redis + Dapr sidecars**

The CLI is NOT a container. It runs on the user's machine.

### Shared Base Image

```dockerfile
FROM python:3.12-slim
RUN pip install amplifier-service-sdk uvicorn
```

Every service layers on top of this base.

### Three Dockerfile Patterns

**Pattern 1: Content-only service (zero custom code)**

```dockerfile
FROM amplifier-service-base
COPY content/ /app/content/
COPY describe.yaml /app/
CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
```

**Pattern 2: Single-tool service (minimal code)**

```dockerfile
FROM amplifier-service-base
COPY src/ /app/src/
CMD ["amplifier-serve", "--module", "my_tool"]
```

**Pattern 3: Rich service with custom deps (e.g., providers)**

```dockerfile
FROM amplifier-service-base
RUN pip install anthropic openai google-generativeai
COPY src/ /app/src/
CMD ["amplifier-serve", "--module", "providers"]
```

Content-only services can share a single generic image parameterized by mounted `describe.yaml` and content directory.

---

## 8. SDK

### amplifier-service-sdk

A small Python library that provides everything needed to build a service. Not required -- services can be built in any language with any HTTP framework -- but provides convenience for Python services.

#### Core Features

1. **Pydantic v2 request/response models** -- Models for all endpoint contracts: `DescribeResponse`, `ToolRequest`, `ToolResult`, `ProviderRequest`, `ProviderResponse`, `HookEvent`, `HookResult`, `ContentRequest`, `ContentResponse`. All models round-trip cleanly through `model_dump(mode="json")`.

2. **FastAPI app factory** -- Given a service definition (YAML or Python config), starts a FastAPI app with `/describe`, `/content/{path}`, and `/healthz` endpoints pre-wired. The developer only adds their capability endpoints.

3. **Content serving** -- Automatic serving of `.md`/`.yaml` files from a configured content directory. Zero code needed for content-only services.

4. **`amplifier-serve` CLI** -- Entry point for starting services:
   - `amplifier-serve --config describe.yaml` -- content-only service from YAML config
   - `amplifier-serve --module my_tool` -- discovers and serves a Python module's capabilities

5. **Optional convenience decorators** -- For developer ergonomics. Not required for service compliance.

#### What a Developer Needs to Create a New Service

1. Write a Python file with their tool/hook/provider implementation
2. Write a `describe.yaml` listing capabilities and content
3. `FROM amplifier-service-base` + `COPY` + `CMD`
4. Add to `docker-compose.yaml`

---

## 9. Service Inventory

### Capability Services

#### svc-orchestrator

Drives the agent loop. Receives routing table + prompt, calls providers/tools/hooks directly via Dapr.

| Component Type | Names |
|---|---|
| Orchestrator | `streaming` (StreamingOrchestrator) |
| Context Manager | `simple` (SimpleContextManager) |

#### svc-providers

LLM provider adapters.

| Component Type | Names |
|---|---|
| Providers | `anthropic`, `openai`, `azure_openai`, `gemini`, `ollama`, `vllm`, `github_copilot`, `mock` |

#### svc-machine

Consolidated machine service — shell execution, file operations, and search. Provides per-session instances via an abstract driver interface (SSH/SFTP for local and remote, future S3 for cloud storage).

| Component Type | Names |
|---|---|
| Tools | bash, read_file, write_file, edit_file, grep, glob |

#### svc-web

Web search and fetch.

| Component Type | Names |
|---|---|
| Tools | `web_search`, `web_fetch` |

#### svc-delegate

Agent delegation (sub-session spawning).

| Component Type | Names |
|---|---|
| Tool | `delegate` |

#### svc-task

Background task execution.

| Component Type | Names |
|---|---|
| Tool | `task` |

#### svc-todo

Todo list management with reminder hooks.

| Component Type | Names |
|---|---|
| Tool | `todo` |
| Hooks | `todo_reminder`, `todo_display` |

#### svc-modes

Runtime mode management -- enforces tool restrictions when a mode is active.

| Component Type | Names |
|---|---|
| Tool | `mode` (operations: set, clear, list, current) |
| Hook | `mode` (events: `tool:pre`, `provider:request`, priority: 5) |
| Content | `context/modes-instructions.md` |

#### svc-skills

Skill discovery and loading.

| Component Type | Names |
|---|---|
| Tool | `load_skill` (operations: list, search, info, load, register source) |
| Content | `context/skills-instructions.md` |

#### svc-routing

Model routing based on curated role-to-provider matrices.

| Component Type | Names |
|---|---|
| Hook | `routing` (events: `provider:request`) |
| Content | `context/role-definitions.md`, `context/routing-instructions.md`, routing matrix YAML files |

#### svc-logging

Session logging hook.

| Component Type | Names |
|---|---|
| Hook | `logging` (events: `*`) |

#### svc-redaction

Content redaction hook.

| Component Type | Names |
|---|---|
| Hook | `redaction` |

#### svc-sessions

Session naming and management.

| Component Type | Names |
|---|---|
| Hook | `session_naming` |
| Content | Session templates |

#### svc-status-context

Status context tracking hook.

| Component Type | Names |
|---|---|
| Hook | `status_context` |

#### svc-progress-monitor

Progress monitoring hook.

| Component Type | Names |
|---|---|
| Hook | `progress_monitor` |

#### svc-streaming-ui

Streaming UI event hook.

| Component Type | Names |
|---|---|
| Hook | `streaming_ui` |

### Content-Only Services

These services respond to `/describe` and `/content/{path}` only. No capability endpoints.

| Service | Content |
|---|---|
| `svc-core` | Core documentation, contracts, shared context |
| `svc-amplifier` | Amplifier ecosystem meta-information |
| `svc-browser-tester` | Browser testing agents and guidance |
| `svc-design-intelligence` | Design agents and intelligence |
| `svc-filesystem-content` | Filesystem editing guidance |
| `svc-recipes` | Recipe authoring guidance |
| `svc-superpowers` | Development methodology content |
| `svc-system-design-intelligence` | System design intelligence content |

### Infrastructure Services

| Service | Role |
|---|---|
| `session-service` | Session lifecycle gateway (prompt intake, service discovery, prompt assembly, transcript persistence) |
| `svc-machine` | Filesystem and command execution access (workspace volume-mounted) |
| `redis` | Dapr state store + pub/sub broker |

---

## 10. CLI

### Role

The CLI runs on the user's machine (not a container). It is an **HTTP client** to the Session Service, not a library consumer of an in-process Host.

### Responsibilities

- **Workspace content resolution** -- reads `.amplifier/AGENTS.md`, local `@mentions`, workspace settings, and serializes them as JSON in the request payload
- **HTTP communication** -- sends `POST /sessions/{id}/turn` to the Session Service with prompt + resolved content
- **SSE streaming** -- subscribes to the session's streaming topic via Dapr pub/sub to receive real-time tokens and events
- **Interactive REPL** -- prompt-toolkit based REPL with slash commands
- **Rendering** -- Rich console rendering of streaming tokens, tool calls, thinking blocks, and approval dialogs
- **API key management** -- loads and manages provider API keys

### CLI-to-Session-Service API

```
POST /sessions/{id}/turn
Content-Type: application/json

{
  "prompt": "user's message",
  "agent_ref": "foundation",
  "workspace_content": {
    "agents_md": "...",
    "mentions": {"@project:README.md": "..."},
    "settings": {...}
  }
}
```

The CLI resolves all workspace-local content before sending. The Session Service never touches the user's filesystem.

### Streaming

The CLI subscribes to the session's streaming topic to receive events in real-time:

```
Topic: session.{id}.stream
Events: stream.token, stream.thinking, stream.tool_call_start,
        stream.content_block_start, stream.content_block_end, complete
```

### Slash Commands

The REPL supports slash commands for session management:

| Command | Description |
|---|---|
| `/session` | Session management (list, resume, fork) |
| `/provider` | Provider selection |
| `/routing` | Routing configuration |
| `/mode` | Mode management |
| `/reset` | Reset session state |

### Agent/Behavior Definitions

The CLI retains agent/behavior definition resolution for determining which services an agent needs. Definition YAML files declare behaviors, and behaviors map to service containers:

```
Agent Definition (foundation-agent.yaml)
  +-- composes Behaviors (agents.yaml, logging.yaml, redaction.yaml, ...)
       +-- each behavior activates components from Services
            +-- each service is a Dapr container
```

---

## 11. Data Models

All wire-format data uses **Pydantic v2 models** from `amplifier-service-sdk`. Models round-trip cleanly through `model_dump(mode="json")`.

### ToolRequest / ToolResult

```python
class ToolRequest(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)

class ToolResult(BaseModel):
    success: bool = True
    output: Any = None
    error: dict[str, Any] | None = None
```

### ToolSpec

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
```

### ProviderRequest / ProviderResponse

```python
class ProviderRequest(BaseModel):
    messages: list[Message]
    tools: list[ToolSpec] | None = None
    system: str | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None

class ProviderResponse(BaseModel):
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    text: str | None = None
    usage: Usage | None = None
    finish_reason: str | None = None
    metadata: dict[str, Any] | None = None
```

### Message

```python
class Message(BaseModel):
    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None
```

### ToolCall

```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
```

### HookEvent / HookResult

```python
class HookEvent(BaseModel):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None

class HookAction(str, Enum):
    CONTINUE = "CONTINUE"
    DENY = "DENY"
    MODIFY = "MODIFY"
    INJECT_CONTEXT = "INJECT_CONTEXT"
    ASK_USER = "ASK_USER"

class HookResult(BaseModel):
    action: HookAction = HookAction.CONTINUE
    data: dict[str, Any] | None = None
    reason: str | None = None
    message: Message | None = None
```

### DescribeResponse

```python
class DescribeResponse(BaseModel):
    name: str
    capabilities: Capabilities
    content: ContentManifest

class Capabilities(BaseModel):
    tools: list[ToolSpec] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    hooks: list[HookDescriptor] = Field(default_factory=list)

class HookDescriptor(BaseModel):
    name: str
    events: list[str]
    priority: int = 100

class ContentManifest(BaseModel):
    paths: list[str] = Field(default_factory=list)
```

### Usage

```python
class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
```

---

## 12. Error Handling

Error handling is delegated to Dapr's built-in mechanisms for transport-level concerns:

- **Service invocation** -- Dapr provides automatic retries with configurable backoff, circuit breakers for failing services, and mTLS for transport security.
- **Pub/sub** -- Dapr handles message delivery guarantees and dead-letter topics for failed hook event processing.
- **Health checks** -- Every service exposes `/healthz`. Dapr monitors service health and removes unhealthy instances from the service mesh.
- **State store** -- Dapr provides transactional state operations for session persistence via Redis.

Application-level errors (tool execution failures, provider errors) are returned as structured error responses through the standard HTTP request/response contract:

```json
{
  "success": false,
  "error": {
    "code": "TOOL_EXECUTION_FAILED",
    "message": "Command timed out after 30 seconds",
    "details": {"command": "...", "timeout": 30}
  }
}
```

The orchestrator handles application errors within the agent loop -- it decides whether to retry, abort, or synthesize an error message for the user.

---

## 13. Testing Strategy

### Unit Tests

Tool, hook, and provider implementations are tested in isolation, independent of the service framework. Business logic is tested directly against the Pydantic request/response models.

### Contract Tests

Each service's `/describe` response and endpoint contracts are validated against the SDK's Pydantic models. Ensures services conform to the expected schema.

### Service-Level Tests

Individual services are tested with their Dapr sidecar to verify pub/sub subscriptions, state operations, and service invocation work correctly.

### Integration Tests

Docker Compose brings up the full service mesh. Tests exercise the complete session lifecycle:

```
CLI --> Session Service --> Orchestrator --> Tools/Providers --> CLI
```

Verifies tool calls, hook events, provider completions, streaming, and transcript persistence end-to-end.

---

## 14. Open Questions

| Question | Status |
|---|---|
| **gRPC vs HTTP** | Deferred. SDK abstracts the transport. HTTP is simpler to debug (curl); gRPC has better streaming semantics. Decide when benchmarking is possible. |
| **Auth between services** | Dapr provides mTLS by default, sufficient for local Docker Compose. Revisit for production deployment. |
| **Provider streaming mechanics** | Does the provider publish tokens directly to pub/sub, or does the orchestrator receive a streaming response and republish? Orchestrator-mediated is simpler for now. |
| **Sub-session spawning** | When the orchestrator delegates to a child agent, the Session Service needs to configure a new session with different services. Since all services are always running in Docker Compose, the Session Service selects different subsets per session via the routing table. |
| **Behavior composition at runtime** | Can an agent activate/deactivate behaviors mid-session, or is the behavior set fixed at session start? |
