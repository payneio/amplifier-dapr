# Amplifier Microservices Workspace

This system is defined in docs/specs/amplifier-spec.md. This is the SoT about how the system is supposed to work. The code is the actual truth, though, so consult it to find out how things really work. If the code needs to be changed in a way that deviates from the spec, confirm with the user, and update the spec to match.

The design document at docs/design/amplifier-ipc-microservices-design.md provides detailed architectural context and rationale.

## Current Status

The Dapr microservices framework is implemented and running:

- **~23 services** are defined in docker-compose.yaml, each with Dapr sidecars
- **Session CLI** (`amplifier-svc`) works with streaming SSE, tool calls, and real LLM providers (Anthropic, OpenAI, etc.)
- **Docker compose** builds and runs successfully end-to-end
- **All unit tests pass** across all services (74 in ampctl, 126 in session-service, 148 in CLI, 58 in orchestrator, 136 in svc-machine, 42 in delegation)
- The orchestrator agent loop, context management, hook pipeline, and content assembly are all functional
- **Agent definition system** (`ampctl`) is implemented: YAML-based agent definitions, deterministic service name hashing, docker-compose generation, and a management CLI
- **Session-service** loads agent definitions from YAML files with hardcoded fallback
- **SSE event parity with legacy Amplifier** — all streaming events use legacy-compatible names and data shapes (content_block:start/end, thinking:delta/final, delegate:agent_spawned/completed)
- **Streaming delegation** — svc-delegation streams child session events in real time via SSE; CLI displays nested delegation progress
- **Machine service consolidation complete** — svc-machine now provides all machine tools (bash, read_file, write_file, edit_file, grep, glob) with per-session instance management, async driver abstraction (SSH/SFTP via asyncssh), and proper session lifecycle integration. Old services (svc-bash, svc-filesystem, svc-search) have been removed.
- **SSH machine access works end-to-end** — Docker containers connect to the host via SSH using `host.docker.internal`. The CLI creates sessions with machine provisioning, the session-service stores machine_instance_id, and svc-machine routes tool calls through the async SSH driver.

## Recent Design Decisions

- **Agent definition system**: Only agent definitions exist (no separate behavior definition files). Each definition includes `image` URIs for containers, an `instruction` field (system prompt seed), singleton services (`orchestrator`, `context_manager`, `providers`), and a `behaviors` section for tools/hooks/content. See `docs/design/agent-definitions-and-ampctl.md` for the full format.
- **Management CLI (`ampctl`)**: Separate from the session CLI. Handles `add <uri> <name>`, `remove`, `list`, `update`, `compose`, `inspect`. Generates `docker-compose.yaml` from installed agent definitions. Conflict resolution uses deterministic hashing of image/build values for service names.
- **No UUIDs needed**: Dapr app-ids and image hashes handle identity. Behavior keys are simple names (no org namespace required) since `ampctl` controls docker-compose generation.
- **Providers (plural)**: Single container with all LLM providers, selected at runtime via routing hooks.
- **SSE event naming**: Uses legacy Amplifier event names with colon separators (e.g., content_block:start, delegate:agent_spawned) to ease future migration of monolith bundles into services.
- **Display belongs in CLI**: Todo display, streaming UI, and thinking block rendering are CLI presentation concerns, not server-side hooks. The server emits structured SSE events; the CLI renders them with Rich. This is the correct separation for a client-server architecture.
- **HookResult contract**: Matches legacy amplifier-core — context_injection, ephemeral, and context_injection_role are top-level fields on HookResult, not nested in data.
- **Machine service consolidation**: All machine tools (bash, read_file, write_file, edit_file, grep, glob) are now consolidated in svc-machine with per-session instance management. Uses an async driver abstraction layer supporting SSH/SFTP (via asyncssh). Old services (svc-bash, svc-filesystem, svc-search) have been deleted. This eliminates redundant IPC and simplifies session lifecycle integration.
- **SSH host access from Docker**: Agent definitions support `extra_hosts` (maps to Docker Compose `extra_hosts`). Foundation agent uses `host.docker.internal:host-gateway` so containers can SSH to the host. The CLI creates sessions with `use_default_machine=True`, which tells session-service to provision an SSH machine instance pointing at `host.docker.internal`.
- **Session creation is mandatory before tool use**: The CLI's `run` command (single-turn mode) now calls `POST /sessions/create` before streaming turns. This provisions the machine instance so svc-machine has a valid `machine_instance_id` for SSH connections. The REPL already handled this correctly.

## Key Design Documents

- `docs/design/amplifier-ipc-microservices-design.md` -- the overall microservices architecture and rationale
- `docs/design/agent-definitions-and-ampctl.md` -- the agent definition format and management CLI design
- `docs/specs/amplifier-spec.md` -- the spec (needs updating to reflect the new agent definition format and ampctl design)
- `docs/plans/sse-event-parity-plan.md` -- the plan for SSE event alignment and streaming delegation

## Next Steps

In priority order:

1. **Update the spec** (`docs/specs/amplifier-spec.md`) to reflect the new agent definition format and `ampctl` design
2. ~~**Implement `ampctl`**~~ -- DONE. See `ampctl/` package.
3. ~~**Implement the definition system in session-service**~~ -- DONE. See `services/session-service/src/session_service/agents.py`.
4. ~~**Machine service consolidation**~~ -- DONE. Consolidated all machine tools (bash, filesystem, search) into svc-machine with driver abstraction, SSH/SFTP support, and per-session instance management.
5. **Implement remaining session CLI slash commands**: `/mode`, `/save`, `/status`, `/clear`, `/config`, `/rename`, `/fork`, `/skills`, `/skill`
6. **Replace `docker-compose.yaml`** with a generated version from `ampctl compose` (currently the existing hand-written compose still works but `ampctl compose` can generate a new one)
7. **Wire session-service to use service-map app-ids** for orchestrator/context routing instead of hardcoded `svc-orchestrator` / `svc-context` names
8. **True incremental streaming** — provider calls currently return full responses; token-by-token streaming requires provider service interface changes

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
amplifier-cli/            The Amplifier CLI. HTTP client to session-service with REPL, streaming display, workspace resolution.
services/                 Dapr-native microservices. Each svc-* directory is an independent container.
  session-service/        Session lifecycle gateway (discovery, content assembly, state, SSE streaming, child spawning).
  svc-orchestrator/       Agent loop with forward Dapr calls (tool dispatch, provider dispatch, hook dispatch).
  svc-context/            Context manager with progressive compaction.
  svc-machine/            Consolidated machine service (bash, read_file, write_file, edit_file, grep, glob). Per-session instances via SSH/SFTP or local driver.
  svc-web/                WebSearchTool, WebFetchTool -- self-contained (aiohttp, duckduckgo-search).
  svc-skills/             SkillsTool with skill discovery.
  svc-todo/               TodoTool + in-process TodoReminderHook. Todo display is a CLI concern.
  svc-modes/              ModeTool + in-process ModeHook (tightly coupled).
  svc-providers/          8 LLM providers: Anthropic, OpenAI, Azure, Gemini, Ollama, vLLM, GitHub Copilot.
  svc-mock-provider/      Deterministic mock provider for testing.
  svc-delegation/         DelegateTool -- streaming delegation with real-time child session events via SSE.
  svc-hooks-approval/     Pre-hook: rule-based tool allow/deny.
  svc-hooks-routing/      Pre-hook: provider/model routing matrix.
  svc-hooks-async/        Post-hook: pub/sub JSONL logging.
  svc-hooks-shell/        Hybrid hook: shell script bridge.
  svc-content-*/          8 content-only services (core, amplifier, browser-tester, etc.).
docker/                   Base Dockerfile, Dapr component configs (Redis state store + pub/sub).
docker-compose.yaml       Full stack: ~26 services + Dapr sidecars + Redis.
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
    --> svc-machine (per-session instances: bash, read_file, write_file, edit_file, grep, glob via SSH/SFTP or local driver)
    --> svc-web, svc-skills, svc-todo, svc-modes (standalone tool services)
    --> svc-hooks-* (pre-hooks via SI, post-hooks via pub/sub)
    --> svc-context (conversation memory)
  --> svc-content-* (context docs, agent definitions)
  --> Redis (Dapr state store + pub/sub broker)
```

## Key Patterns

- **Machine tools** (bash, read_file, write_file, edit_file, grep, glob) are consolidated in svc-machine with per-session instance management. Other tool services (web, skills, etc.) are standalone.
- **Pre-hooks** (approval, routing) are called via Dapr service invocation (sequential, may DENY/MODIFY).
- **Post-hooks** (logging, shell) subscribe to Dapr pub/sub topics (parallel, fire-and-forget).
- **Content services** are zero-code containers: just describe.yaml + Dockerfile using amplifier-serve --config.
- **The CLI** resolves local workspace content (@mentions, .amplifier/ files) and sends it as JSON payload to the session-service.

## Reminders

- We use `uv` extensively in this project. Tests should usually be run in an appropriate venv or with `uv run pytest` from within each service directory.
- Each service has its own pyproject.toml and uv.lock. Dependencies are isolated per service.
- The root pyproject.toml configures pythonpath for cross-service integration tests in tests/.
