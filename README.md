## Amplifier IPC

A Dapr-native microservices framework for AI agent orchestration. Every component (orchestrator, tools, hooks, providers, context manager) runs as its own container, communicating via HTTP and Dapr service invocation / pub/sub. This gives process-level isolation, per-service dependency management, and a path to multi-language services.

For architecture details, see `docs/specs/amplifier-ipc-spec.md`.
For design rationale, see `docs/design/amplifier-ipc-microservices-design.md`.

## Architecture

```
CLI (amplifier-ipc) --HTTP/SSE--> session-service (gateway)
  --> svc-orchestrator (agent loop)
    --> svc-providers / svc-mock-provider (LLM)
    --> svc-bash, svc-filesystem, svc-search, svc-web, etc. (tools) --> svc-machine (filesystem)
    --> svc-hooks-* (pre-hooks via service invocation, post-hooks via pub/sub)
    --> svc-context (conversation memory)
  --> svc-content-* (context docs, agent definitions)
  --> Redis (Dapr state store + pub/sub broker)
```

The CLI sends requests over HTTP/SSE to the **session-service**, which acts as the gateway. It resolves agent definitions, assembles content, manages session state, and delegates work to the **svc-orchestrator**. The orchestrator runs the agent loop, dispatching tool calls, provider requests, and hook invocations to their respective services via Dapr.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- `uv` (Python package manager)

### Install the CLI

```bash
cd amplifier-ipc-cli
uv sync
```

### Start the stack

```bash
docker compose up
```

This brings up ~29 services with Dapr sidecars and a Redis broker.

### Run

```bash
# Single-shot
amplifier-ipc run "What files are in this directory?"

# Interactive REPL
amplifier-ipc run
```

## Workspace Layout

```
amplifier-service-sdk/    Shared SDK: Pydantic v2 models, FastAPI app factory, content serving, amplifier-serve CLI.
amplifier-ipc-cli/        The `amplifier-ipc` CLI. HTTP client to session-service with REPL, streaming display, workspace resolution.
services/                 Dapr-native microservices. Each svc-* directory is an independent container.
  session-service/        Session lifecycle gateway (discovery, content assembly, state, SSE streaming, child spawning).
  svc-orchestrator/       Agent loop with forward Dapr calls (tool dispatch, provider dispatch, hook dispatch).
  svc-context/            Context manager with progressive compaction.
  svc-machine/            Machine abstraction (filesystem + command execution). Volume-mounted workspace in local mode.
  svc-bash/               BashTool -- calls svc-machine /exec.
  svc-filesystem/         ReadFileTool, WriteFileTool, EditFileTool -- calls svc-machine /files/*.
  svc-search/             GrepTool, GlobTool -- calls svc-machine /files/grep, /files/glob.
  svc-web/                WebSearchTool, WebFetchTool -- self-contained (aiohttp, duckduckgo-search).
  svc-skills/             SkillsTool with skill discovery.
  svc-todo/               TodoTool + in-process TodoReminderHook + TodoDisplayHook.
  svc-modes/              ModeTool + in-process ModeHook (tightly coupled).
  svc-providers/          8 LLM providers: Anthropic, OpenAI, Azure, Gemini, Ollama, vLLM, GitHub Copilot.
  svc-mock-provider/      Deterministic mock provider for testing.
  svc-delegation/         DelegateTool -- calls session-service /spawn for child sessions.
  svc-hooks-approval/     Pre-hook: rule-based tool allow/deny.
  svc-hooks-routing/      Pre-hook: provider/model routing matrix.
  svc-hooks-async/        Post-hook: pub/sub JSONL logging.
  svc-hooks-shell/        Hybrid hook: shell script bridge.
  svc-content-*/          8 content-only services (core, amplifier, browser-tester, etc.).
docker/                   Base Dockerfile, Dapr component configs (Redis state store + pub/sub).
docker-compose.yaml       Full stack: ~29 services + Dapr sidecars + Redis.
docs/                     Spec, design document, implementation plans.
tests/                    Integration tests for the microservices stack.
```

## Creating a New Service

There are three patterns for adding a service, from simplest to most complex:

### Content-only service

Provides context documents (markdown, YAML) with no runtime logic. Uses the shared `amplifier-serve` CLI from the SDK.

```
services/svc-content-mypackage/
  describe.yaml       # Service metadata and content manifest
  content/            # Static content files
  Dockerfile          # FROM base, COPY ., CMD ["amplifier-serve", "--config", "describe.yaml"]
```

### Single-tool service

A FastAPI app that exposes one tool endpoint.

```python
# services/svc-mytool/src/svc_mytool/main.py
from amplifier_service_sdk import create_app, ToolSpec

app = create_app("svc-mytool")

@app.post("/tools/my_tool")
async def my_tool(request: dict) -> dict:
    return {"result": "done"}

@app.get("/describe")
async def describe():
    return {"tools": [ToolSpec(name="my_tool", description="Does something useful").model_dump()]}
```

### Rich service (tools + hooks)

A service that contributes multiple tools and/or hooks. Follow the patterns in `svc-todo/` (tool + hooks) or `svc-modes/` (tool + hook, tightly coupled).

## Key Patterns

- **Tool services** call svc-machine via Dapr service invocation for filesystem/command access. They never touch the filesystem directly.
- **Pre-hooks** (approval, routing) are called via Dapr service invocation (sequential, may DENY/MODIFY).
- **Post-hooks** (logging, shell) subscribe to Dapr pub/sub topics (parallel, fire-and-forget).
- **Content services** are zero-code containers: just describe.yaml + Dockerfile using `amplifier-serve --config`.
- **The CLI** resolves local workspace content (@mentions, .amplifier/ files) and sends it as JSON payload to the session-service.

## Configuration

Settings are merged from three scopes (later overrides earlier):

1. Global: `~/.amplifier/settings.yaml`
2. Project: `.amplifier/settings.yaml`
3. Local: `.amplifier/settings.local.yaml`

## Development

Each service has its own `pyproject.toml` and `uv.lock`. Dependencies are isolated per service. Use `uv` for package management:

```bash
# Run tests for a specific service
cd services/svc-bash
uv run pytest

# Run cross-service integration tests
cd tests
uv run pytest
```
