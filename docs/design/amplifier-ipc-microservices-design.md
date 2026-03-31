# Amplifier IPC Microservices Architecture Design

## Goal

Transform amplifier-ipc from a stdio-based, host-mediated IPC architecture into a Dapr-native microservices framework where each behavior runs as an independent container communicating via HTTP/gRPC and pub/sub.

## Background

amplifier-ipc is currently a process-isolated service architecture for AI agent orchestration. A central Host spawns service subprocesses per user turn, communicating via JSON-RPC 2.0 over stdio. The project is a mono-repo with 13 service directories under `services/`.

The current architecture has fundamental limitations:

- **Per-turn lifecycle**: Services spawn fresh and die after each turn (~200ms overhead). The ServiceIndex is rebuilt from scratch every turn.
- **stdio transport**: Single-machine only, newline-delimited JSON. No network distribution possible.
- **Host = broker**: The 1248-line Host monolith mediates every message between every service. All tool calls, hook events, and provider requests flow through it.
- **Python-only**: Despite multi-language goals, the custom JSON-RPC protocol and Python-specific `Server` class make non-Python services impractical.
- **The `_OrchestratorLocalClient` monolith**: The foundation service co-locates orchestrator + tools + hooks + context in a single process to avoid IPC deadlock. This defeats the purpose of process isolation.

These constraints cannot be incrementally fixed. A clean architectural break is required.

## Approach

Replace the entire IPC layer with Dapr-native microservices. This is a clean break -- no backward compatibility with the spawn-per-turn model. The key decisions:

1. **Dapr as the service mesh** -- Provides service invocation (mTLS, retries, circuit breakers), pub/sub (streaming, hook fan-out), state store (session persistence), and observability out of the box.
2. **One behavior = one container** -- Every behavior (tool, hook, provider group) runs as its own container. This is aggressive decomposition, enabled by a shared base image and thin SDK.
3. **Orchestrator drives the loop directly** -- The orchestrator calls tools and providers via Dapr service invocation, not through the Session Service. The Session Service handles session lifecycle only.
4. **Standard HTTP endpoints** -- No custom protocol. Services are ordinary HTTP servers with well-known endpoint paths.
5. **Machine abstraction** -- A dedicated Machine Service centralizes all filesystem and command execution access. Tool services call the Machine Service via Dapr instead of touching the filesystem directly. This bridges the container isolation boundary and enables both local and remote workspace access.
6. **No caching** -- Session Service calls `/describe` every turn. Simplicity over premature optimization.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────────┐
│  User's Machine                                                     │
│  ┌──────────┐                                                       │
│  │   CLI    │──── HTTP/gRPC ────┐                                   │
│  └──────────┘                   │                                   │
│       ▲                         │                                   │
│       │ pub/sub streaming       │                                   │
│       │ (tokens + events)       │                                   │
└───────┼─────────────────────────┼───────────────────────────────────┘
        │                         ▼
┌───────┼─────────────────────────────────────────────────────────────┐
│  Docker Compose                 │                                   │
│                    ┌────────────▼──────────────┐                    │
│                    │    Session Service        │                    │
│                    │  (session lifecycle only) │                    │
│                    └────────────┬──────────────┘                    │
│                                 │                                   │
│              ┌──────────────────▼──────────────────┐                │
│              │       Orchestrator Service          │                │
│              │    (drives the agent loop)          │                │
│              └──┬──────────┬──────────┬───────────┘                │
│                 │          │          │                              │
│        ┌────────▼──┐ ┌────▼────┐ ┌───▼──────┐                     │
│        │ Providers │ │  Tools  │ │  Hooks   │                      │
│        │ (Dapr SI) │ │(Dapr SI)│ │(pub/sub) │                      │
│        └───────────┘ └────┬────┘ └──────────┘                      │
│                           │                                         │
│                    ┌──────▼──────────────────────────┐              │
│                    │  Machine Service                │              │
│                    │  (filesystem + command exec)    │              │
│                    │  [workspace volume mounted]     │              │
│                    └────────────────────────────────-┘              │
│                                                                     │
│        ┌───────────────────────────────────────┐                    │
│        │  Content Services (/describe +        │                    │
│        │  /content only, no capabilities)      │                    │
│        └───────────────────────────────────────┘                    │
│                                                                     │
│        ┌─────────┐                                                  │
│        │  Redis  │  (Dapr state store + pub/sub broker)             │
│        └─────────┘                                                  │
│                                                                     │
│  Every container has a Dapr sidecar (mTLS, retries, observability) │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Roles

- **CLI** -- Runs on the user's machine (not a container). Resolves workspace content (`@mentions`, `.amplifier/` files, `AGENTS.md`), sends resolved content + prompt as an HTTP/gRPC payload to the Session Service. Subscribes to a streaming topic to receive real-time tokens and events.

- **Session Service** (formerly Host) -- Containerized service for session lifecycle only. Receives prompts with resolved content, resolves agent/behavior definitions, calls `/describe` on active services to build the routing table and collect content manifests, assembles the system prompt from service content + workspace content, invokes the orchestrator via Dapr service invocation, persists transcripts via Dapr state store, and streams events back to the CLI. Not in the hot path for tool/provider/hook calls.

- **Orchestrator Service** -- Drives the agent loop. Receives the routing table as input (which tool lives at which Dapr app-id). Calls providers, tools, and hooks directly via Dapr service invocation and pub/sub. No longer routes through the Session Service for runtime messages.

- **Capability Services** -- Provider, tool, hook, mode, skills, etc. containers. Each exposes well-known HTTP/gRPC endpoints following a simple contract. Split by behavior -- each behavior becomes its own container.

- **Machine Service** -- Centralizes all filesystem and command execution access behind a single Dapr service. In the current IPC architecture, tools like bash, filesystem, grep, and glob operate directly on the user's machine because they run as subprocesses. In containers, that assumption breaks -- tools have no access to the user's workspace. The Machine Service bridges this gap: tool services call it via Dapr service invocation for all filesystem and command operations. It exposes `/exec` (shell command execution), `/files/read`, `/files/write`, `/files/edit`, `/files/list`, `/files/glob`, and `/files/grep` endpoints. In **local mode**, the user's workspace is volume-mounted into the Machine Service container and operations execute via subprocess/filesystem calls. In **remote mode** (future), the same interface proxies to a remote host via SSH/SFTP. Tool services never touch the filesystem directly -- they always go through the Machine Service, making them portable across both modes.

- **Dapr Sidecars** -- Every container gets a Dapr sidecar providing service invocation (with mTLS, retries, circuit breakers), pub/sub (for streaming and hook fan-out), state store (for session state), and observability.

## Components

### Service Contract

Services are standard HTTP (or gRPC) apps that expose well-known endpoints. No custom protocol library required.

#### Endpoint Contracts by Component Type

| Component Type | Endpoint | Method | Description |
|---|---|---|---|
| Provider | `/providers/{name}/complete` | POST | Takes a chat request, returns completion |
| Provider | `/providers/{name}/stream` | POST | Publishes tokens to session's pub/sub topic |
| Tool | `/tools/{name}/execute` | POST | Takes tool input, returns tool result |
| Hook | *(none -- subscribes to pub/sub topics)* | -- | Hooks subscribe to event topics, no endpoint needed |
| Context | `/context/messages` | GET/POST | Get/set conversation messages |
| Orchestrator | `/orchestrator/execute` | POST | Accepts session config + prompt. Publishes stream events to the session's pub/sub topic. Returns final result when the agent loop completes. |
| Machine | `/exec` | POST | Execute shell command. Returns stdout, stderr, exit code. |
| Machine | `/files/read` | POST | Read file contents (path, offset, limit) |
| Machine | `/files/write` | POST | Write file contents |
| Machine | `/files/edit` | POST | Edit file (string replacement) |
| Machine | `/files/list` | POST | List directory contents |
| Machine | `/files/glob` | POST | Glob pattern matching |
| Machine | `/files/grep` | POST | Search file contents with regex |
| Describe | `/describe` | GET | Returns capability manifest (what tools/providers/hooks this service offers) + content manifest |
| Content | `/content/{path}` | GET | Serves content files (context docs, agent definitions, recipes) on demand |
| Health | `/healthz` | GET | Dapr-standard health check |

#### Key Changes from Current IPC

- **Hooks shift to pub/sub**: From "Host calls each hook sequentially" to "orchestrator publishes event, hooks subscribe via Dapr pub/sub." Enables parallel hook execution and decouples the orchestrator from knowing which hooks exist.
- **`/describe` replaces JSON-RPC `describe`**: Same purpose (capability discovery), standard HTTP.
- **No custom Server/Client classes**: Services use any HTTP framework (FastAPI, Flask, Express, Go `net/http`, etc.).
- **Optional Python SDK**: Provides convenience decorators and Pydantic request/response models. Not required.

### Service Ontology

There is **one kind of service**. Every service:

1. Has a Dapr app-id
2. Responds to `GET /describe` with its capability + content manifest
3. Serves content via `GET /content/{path}`
4. Optionally exposes tool, hook, and/or provider endpoints
5. Optionally subscribes to pub/sub topics (hooks)

The variation is in what capabilities a service offers, not in what "type" it is.

#### Behavior Composition

The behavior YAML remains the composition unit. It declares which services to include and which of their capabilities to activate:

```
Agent Definition (foundation-agent.yaml)
  └─ composes Behaviors (agents.yaml, logging.yaml, redaction.yaml, ...)
       └─ each behavior activates components from Services
            └─ each service is a Dapr container exposing
               /describe + /content + capability endpoints
```

#### Content Model

- **Service content** stays in the service container. Services carry their content and serve it via `/describe` (manifests at session start) and `/content/{path}` (on-demand file retrieval).
- **Content-only services** are still containers -- they just respond to `/describe` and `/content` with no capability endpoints.
- **Workspace-local content** (`.amplifier/AGENTS.md`, local `@mentions`) is resolved by the CLI and sent as part of the API payload to the Session Service. This is the "content-in-request" pattern -- CLI reads local files, serializes as JSON, includes in the request body.
- Service content + workspace content are combined by the Session Service when assembling the system prompt.

### Machine Service

In the current IPC architecture, tools like bash, filesystem, grep, and glob execute directly on the user's machine because they run as subprocesses. In a containerized world, each tool service is isolated in its own container with no access to the user's workspace. The Machine Service solves this by centralizing all workspace interactions behind a single Dapr service.

#### The Problem

Any tool that touches the filesystem or executes commands needs access to the user's project directory:
- `svc-bash` needs to run shell commands in the workspace
- `svc-filesystem` needs to read, write, and edit files
- `svc-search` needs to grep and glob across the workspace
- `svc-web` may need to save downloaded content

Without the Machine Service, each of these would need its own volume mount and its own subprocess execution logic. The Machine Service consolidates this into one place.

#### Two Modes

The Machine Service exposes the same HTTP endpoints regardless of mode. Tool services never know which backend is active.

**Local mode (implemented):** The user's workspace directory is volume-mounted into the Machine Service container. Commands execute via `asyncio.create_subprocess_exec()`. File operations use standard filesystem calls. All paths are sandboxed within the mounted workspace directory (path traversal is blocked).

```yaml
# docker-compose.yaml
svc-machine:
  volumes:
    - ${WORKSPACE_PATH:-.}:/workspace
  environment:
    - MACHINE_WORKSPACE_DIR=/workspace
```

**Remote mode (future):** The same endpoints proxy to a remote host via SSH (for commands) and SFTP (for file operations). Configuration specifies the remote host, credentials, and workspace path. This enables cloud-hosted dev environments, remote GPU machines, or shared team workspaces.

#### How Tools Use It

Tools call the Machine Service via Dapr service invocation instead of executing directly:

```python
# Before (IPC world): BashTool runs commands directly
result = subprocess.run(command, shell=True, capture_output=True)

# After (microservices world): BashTool calls the Machine Service
result = await httpx_client.post(
    f"{machine_service_url}/exec",
    json={"command": command, "timeout": 30, "working_dir": "/workspace"}
)
```

This pattern applies to all filesystem-touching tools: bash, read, write, edit, grep, glob, list.

## Data Flow

### Communication Patterns

Three communication patterns cover all interactions:

#### Pattern 1: Request/Response (Dapr Service Invocation)

**Used for:** tool execution, provider completion, `/describe`, `/content/{path}`, pre-hooks

The orchestrator calls a tool or provider and waits for the result. Dapr service invocation provides mTLS, retries, and circuit breakers automatically.

#### Pattern 2: Pub/Sub with Streaming Subscriptions (Token Streaming)

**Used for:** streaming LLM tokens from provider through orchestrator to CLI

The orchestrator publishes tokens to a session-scoped topic as they arrive from the provider. The Session Service or CLI subscribes via Dapr streaming subscriptions and renders in real-time. Dapr streaming subscriptions (since v1.14) support pull-based message delivery over gRPC without needing an HTTP endpoint.

#### Pattern 3: Pub/Sub with Declarative Subscriptions (Hook Events)

**Used for:** lifecycle events (`session:start`, `tool:pre`, `tool:post`, `provider:request`, etc.)

The orchestrator publishes hook events to a topic. Hook services subscribe declaratively. Replaces current sequential fan-out with parallel, decoupled event handling.

#### Hook Modification Pattern

For hooks that need to inspect and modify requests (pre-hooks), the orchestrator uses request/response service invocation (sequential). For post-hooks (observation only), pub/sub (parallel, fire-and-forget).

| Hook Timing | Pattern | Why |
|---|---|---|
| `*:pre` events | Service invocation (sequential) | May modify or block the request |
| `*:post` events | Pub/sub (parallel) | Observation only |

### Session Lifecycle

#### Phase 1: Session Setup (CLI + Session Service)

1. User types prompt in CLI
2. CLI resolves local content (`.amplifier/AGENTS.md`, settings, workspace `@mentions`)
3. CLI sends HTTP request to Session Service: `POST /sessions/{id}/turn` with prompt, workspace_content, agent_ref
4. Session Service resolves agent definition -> determines active behaviors -> determines needed services
5. Session Service calls `GET /describe` on each needed service -> builds capability routing table + collects content manifests
6. Session Service calls `GET /content/{path}` for needed context files
7. Session Service assembles full system prompt: service content + workspace content + conversation history

#### Phase 2: Agent Loop (Orchestrator Drives)

8. Session Service invokes orchestrator: `POST /orchestrator/execute` with system_prompt, messages, config, routing_table
9. Orchestrator enters the agent loop:
   - a. Calls pre-hooks via service invocation (sequential, may modify)
   - b. Calls provider via service invocation
   - c. Provider tokens published to pub/sub topic -> CLI renders
   - d. On tool call: calls pre-hooks, executes tool, publishes post-hook events
   - e. Repeats until LLM signals completion
10. Orchestrator publishes completion event

#### Phase 3: Teardown

11. Session Service receives completion
12. Persists transcript to Dapr state store
13. Returns final result to CLI

**Key difference from today:** The orchestrator receives the routing table as input rather than discovering it at runtime.

## Deployment

### Full Behavior-Level Decomposition

`amplifier-foundation` is split by behavior. Each behavior becomes its own container. All services share a base image.

#### From amplifier-foundation (Split by Behavior)

| Container | From Behavior | Components |
|---|---|---|
| `svc-orchestrator` | (core) | StreamingOrchestrator + SimpleContextManager |
| `svc-delegate` | agents | DelegateTool |
| `svc-task` | tasks | TaskTool |
| `svc-todo` | todo-reminder | TodoTool + TodoReminderHook + TodoDisplayHook |
| `svc-bash` | (tool) | BashTool |
| `svc-filesystem` | (tool) | ReadTool, WriteTool, EditTool |
| `svc-search` | (tool) | GrepTool, GlobTool |
| `svc-web` | (tool) | WebSearchTool, WebFetchTool |
| `svc-logging` | logging | LoggingHook |
| `svc-redaction` | redaction | RedactionHook |
| `svc-sessions` | sessions | SessionNamingHook + content |
| `svc-status-context` | status-context | StatusContextHook |
| `svc-progress-monitor` | progress-monitor | ProgressMonitorHook |
| `svc-streaming-ui` | streaming-ui | StreamingUiHook |

#### Already-Separate Services (Unchanged)

| Container | Components |
|---|---|
| `svc-providers` | 8 LLM providers |
| `svc-modes` | ModeTool + ModeHook |
| `svc-routing` | RoutingHook |
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
| `svc-machine` | Filesystem and command execution access (workspace volume-mounted in local mode; SSH/SFTP in remote mode) |
| `session-service` | Session lifecycle gateway |
| `redis` | Dapr state store + pub/sub broker |

**Total: ~29 application containers + redis + Dapr sidecars**

The CLI is NOT a container. It runs on the user's machine.

### Shared Service SDK & Base Image

With ~28 containers, developer experience and operational overhead must be minimal. A shared base image and thin SDK make this practical.

#### The SDK (`amplifier-service-sdk`)

A small Python library that provides:

1. **Request/response models** -- Pydantic v2 models for all endpoint contracts: `DescribeResponse`, `ToolRequest`, `ToolResult`, `ProviderRequest`, `ProviderResponse`, `HookEvent`, `HookResult`, `ContentRequest`, `ContentResponse`
2. **A generic service runner** -- Given a service definition (YAML or Python config), starts a FastAPI app with `/describe` and `/content/{path}` endpoints pre-wired. The developer only adds their capability endpoints.
3. **Optional convenience decorators** -- Not required. For developer ergonomics only.
4. **Content serving** -- Automatic serving of `.md`/`.yaml` files from a configured content directory. Zero code needed for content-only services.

#### Base Image

```dockerfile
FROM python:3.12-slim
RUN pip install amplifier-service-sdk uvicorn
# That's it. Every service layers on top.
```

#### Three Patterns for Building Service Images

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

**Pattern 3: Rich service like providers (custom deps)**

```dockerfile
FROM amplifier-service-base
RUN pip install anthropic openai google-generativeai
COPY src/ /app/src/
CMD ["amplifier-serve", "--module", "providers"]
```

Content-only services can share a single generic image parameterized by mounted `service.yaml` and content directory.

#### What a Developer Needs to Create a New Service

1. Write a Python file with their tool/hook/provider implementation
2. Write a `describe.yaml` listing capabilities and content
3. `FROM amplifier-service-base` + `COPY` + `CMD`
4. Add to `docker-compose.yaml`

## Error Handling

Error handling is delegated to Dapr's built-in mechanisms:

- **Service invocation**: Dapr provides automatic retries with configurable backoff, circuit breakers for failing services, and mTLS for transport security.
- **Pub/sub**: Dapr handles message delivery guarantees and dead-letter topics for failed hook event processing.
- **Health checks**: Every service exposes `/healthz`. Dapr monitors service health and removes unhealthy instances from the service mesh.
- **State store**: Dapr provides transactional state operations for session persistence via Redis.

Application-level errors (tool execution failures, provider errors) are returned as structured error responses through the standard request/response contract. The orchestrator handles these within the agent loop, just as it does today.

## Testing Strategy

- **Unit tests**: Tool, hook, and provider implementations are tested in isolation, independent of the service framework. Business logic does not change.
- **Contract tests**: Each service's `/describe` response and endpoint contracts are validated against the SDK's Pydantic models.
- **Integration tests**: Docker Compose brings up the full service mesh. Tests exercise the complete session lifecycle: CLI -> Session Service -> Orchestrator -> Tools/Providers -> CLI.
- **Service-level tests**: Individual services are tested with their Dapr sidecar to verify pub/sub subscriptions, state operations, and service invocation work correctly.

## Migration Path

This is a clean break rewrite of the infrastructure layer, not a refactoring of business logic:

| What | Changes | Doesn't Change |
|---|---|---|
| Transport | stdio -> HTTP/gRPC via Dapr | Tool/hook/provider implementation code |
| Service runner | Custom `Server` class -> SDK + FastAPI | What each tool/hook/provider does |
| Discovery | `scan_package()` + JSON-RPC `describe` -> `/describe` HTTP endpoint | Behavior YAML definitions |
| Host | 1248-line monolith -> thin Session Service | Session lifecycle concept |
| State | Custom `state.json` -> Dapr state store | State semantics |
| Streaming | stdio interleaving -> Dapr pub/sub | Token-level streaming to CLI |
| Content | In-process `scan_content()` -> `/content/{path}` endpoint | Content files themselves |
| CLI | Imports Host as library -> HTTP client to Session Service | User-facing commands, REPL |

The tool, hook, and provider implementations (the actual business logic) largely stay the same -- they get new function signatures matching the SDK's request/response models, but the logic inside is unchanged.

## Open Questions

1. **gRPC vs HTTP** -- Deferred to implementation phase. The SDK can abstract the transport. HTTP is simpler to debug (curl), gRPC has better streaming semantics. Decide when benchmarking is possible.
2. **Auth between services** -- Dapr provides mTLS by default, sufficient for local Docker Compose. Revisit for production deployment.
3. **Provider streaming mechanics** -- Does the provider service publish tokens directly to pub/sub, or does the orchestrator receive a streaming response and republish? Orchestrator-mediated is simpler for now.
4. **Sub-session spawning (delegation)** -- When the orchestrator delegates to a child agent, the Session Service needs to spin up a new session with potentially different services. How does this compose with Docker Compose where all services are already running? Likely: all services are always running, the Session Service just selects different subsets per session.
5. **Behavior composition at runtime** -- Can an agent definition activate/deactivate behaviors mid-session, or is the behavior set fixed at session start?
