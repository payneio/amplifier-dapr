# Amplifier Microservices Workspace

This system is defined in docs/specs/amplifier-spec.md. This is the SoT about how the system is supposed to work. The code is the actual truth, though, so consult it to find out how things really work. If the code needs to be changed in a way that deviates from the spec, confirm with the user, and update the spec to match.

The design document at docs/design/amplifier-ipc-microservices-design.md provides detailed architectural context and rationale.

## Current Status

The Dapr microservices framework is implemented and running:

- **~29 services** are defined in docker-compose.yaml, each with Dapr sidecars
- **Session CLI** (`amplifier-svc`) works with streaming SSE, tool calls, and real LLM providers (Anthropic, OpenAI, etc.)
- **Docker compose** builds and runs successfully end-to-end
- **All unit tests pass** across all services (74 in ampctl, 95 in session-service)
- The orchestrator agent loop, context management, hook pipeline, and content assembly are all functional
- **Agent definition system** (`ampctl`) is implemented: YAML-based agent definitions, deterministic service name hashing, docker-compose generation, and a management CLI
- **Session-service** loads agent definitions from YAML files with hardcoded fallback

## Recent Design Decisions

- **Agent definition system**: Only agent definitions exist (no separate behavior definition files). Each definition includes `image` URIs for containers, an `instruction` field (system prompt seed), singleton services (`orchestrator`, `context_manager`, `providers`), and a `behaviors` section for tools/hooks/content. See `docs/design/agent-definitions-and-ampctl.md` for the full format.
- **Management CLI (`ampctl`)**: Separate from the session CLI. Handles `add <uri> <name>`, `remove`, `list`, `update`, `compose`, `inspect`. Generates `docker-compose.yaml` from installed agent definitions. Conflict resolution uses deterministic hashing of image/build values for service names.
- **No UUIDs needed**: Dapr app-ids and image hashes handle identity. Behavior keys are simple names (no org namespace required) since `ampctl` controls docker-compose generation.
- **Providers (plural)**: Single container with all LLM providers, selected at runtime via routing hooks.

## Key Design Documents

- `docs/design/amplifier-ipc-microservices-design.md` -- the overall microservices architecture and rationale
- `docs/design/agent-definitions-and-ampctl.md` -- the agent definition format and management CLI design
- `docs/specs/amplifier-spec.md` -- the spec (needs updating to reflect the new agent definition format and ampctl design)

## Next Steps

In priority order:

1. **Update the spec** (`docs/specs/amplifier-spec.md`) to reflect the new agent definition format and `ampctl` design
2. ~~**Implement `ampctl`**~~ -- DONE. See `ampctl/` package.
3. ~~**Implement the definition system in session-service**~~ -- DONE. See `services/session-service/src/session_service/agents.py`.
4. **Implement remaining session CLI slash commands**: `/mode`, `/save`, `/status`, `/clear`, `/config`, `/rename`, `/fork`, `/skills`, `/skill`
5. **Replace `docker-compose.yaml`** with a generated version from `ampctl compose` (currently the existing hand-written compose still works but `ampctl compose` can generate a new one)
6. **Wire session-service to use service-map app-ids** for orchestrator/context routing instead of hardcoded `svc-orchestrator` / `svc-context` names

## Reference Material

- Old IPC system (the one we're replacing): `./related-projects/amplifier-ipc/`
- Old IPC definition spec: `./related-projects/amplifier-ipc/docs/specs/definition-files.md`
- Reference CLI (for session CLI slash command implementation): `./related-projects/amplifier-app-cli/`
- Reference foundation: `./related-projects/amplifier-foundation/`

## Workspace Layout

```
ampctl/                   Management CLI for agent definitions. `ampctl add`, `ampctl compose`, etc.
agents/                   Agent definition YAML files (foundation.yaml, default.yaml).
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
related-projects/         Reference projects from the old Amplifier platform for historical context.
tests/                    Integration tests for the microservices stack.
```

## Architecture

Amplifier is a Dapr-native microservices framework for AI agent orchestration. Every behavior (tool, hook, provider) runs as an independent container communicating via HTTP + Dapr service invocation and pub/sub.

```
CLI (user's machine) --HTTP/SSE--> session-service (gateway)
  --> svc-orchestrator (agent loop)
    --> svc-providers / svc-mock-provider (LLM)
    --> svc-bash, svc-filesystem, svc-search, svc-web, etc. (tools) --> svc-machine (filesystem)
    --> svc-hooks-* (pre-hooks via SI, post-hooks via pub/sub)
    --> svc-context (conversation memory)
  --> svc-content-* (context docs, agent definitions)
  --> Redis (Dapr state store + pub/sub broker)
```

## Key Patterns

- **Tool services** call svc-machine via Dapr SI for filesystem/command access. They never touch the filesystem directly.
- **Pre-hooks** (approval, routing) are called via Dapr service invocation (sequential, may DENY/MODIFY).
- **Post-hooks** (logging, shell) subscribe to Dapr pub/sub topics (parallel, fire-and-forget).
- **Content services** are zero-code containers: just describe.yaml + Dockerfile using amplifier-serve --config.
- **The CLI** resolves local workspace content (@mentions, .amplifier/ files) and sends it as JSON payload to the session-service.

## Reminders

- We use `uv` extensively in this project. Tests should usually be run in an appropriate venv or with `uv run pytest` from within each service directory.
- Each service has its own pyproject.toml and uv.lock. Dependencies are isolated per service.
- The root pyproject.toml configures pythonpath for cross-service integration tests in tests/.
