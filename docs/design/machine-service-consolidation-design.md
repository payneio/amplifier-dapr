# Machine Service Consolidation Design

## Goal

Consolidate svc-bash, svc-filesystem, and svc-search into a single machine service with per-session instances, multiple backend drivers, and routing-table-based service discovery — eliminating the hardcoded Dapr app-id problem and removing six containers from the compose stack.

## Background

The Amplifier IPC microservices framework uses `ampctl` to generate docker-compose.yaml with hash-suffixed service names (e.g., `svc-machine-6719a84c`). Three tool services — svc-bash, svc-filesystem, and svc-search — exist as separate proxies that forward requests to the machine service via Dapr service invocation. These proxies hardcode bare names like `svc-machine` in their Dapr invocation URLs, which causes DNS resolution failures because the actual container names are hash-suffixed.

Beyond the DNS problem, the proxy architecture is unnecessary indirection. All three services just forward to machine. Consolidating them eliminates the inter-service routing problem entirely and reduces the container count by six (three services + three Dapr sidecars).

## Approach

Absorb svc-bash, svc-filesystem, and svc-search into the machine service. Make the machine service instance-aware so each session gets its own machine instance (SSH connection, working directory, etc.). Use the existing routing table for tool dispatch — multiple tool names map to the same machine service app-id. No special dispatch paths needed.

## Architecture

### Service Tiers

**Framework tier** (fixed, always present):
- session-service (fixed name)
- Redis
- Dapr

**Composed tier** (per agent definition, hash-suffixed names):
- orchestrator
- context_manager
- providers
- behaviors: machine, web, todo, modes, delegation, skills, hooks, content

Machine is a composed service, not framework-level infrastructure. Not every agent needs machine access (e.g., a pure conversational agent, a research-only agent). Agents opt into machine by including it in their agent definition's behaviors.

### Container Reduction

Before: svc-bash + sidecar, svc-filesystem + sidecar, svc-search + sidecar, svc-machine + sidecar = 8 containers.

After: svc-machine + sidecar = 2 containers. Net reduction of 6 containers.

## Components

### The Machine Service

A single agent-composed service that absorbs the functionality of svc-bash, svc-filesystem, and svc-search. Gets a hash-suffixed name like any other behavior (e.g., `svc-machine-6719a84c`).

**What it manages**: Per-session machine instances. Each session gets one machine instance, created at session start, destroyed at session end.

**API surface**:

| Endpoint | Purpose | Replaces |
|---|---|---|
| `POST /instances` | Create a machine instance | — (new) |
| `DELETE /instances/{id}` | Destroy a machine instance | — (new) |
| `POST /instances/{id}/exec` | Run a command | svc-bash |
| `POST /instances/{id}/files/read` | Read a file | svc-filesystem |
| `POST /instances/{id}/files/write` | Write a file | svc-filesystem |
| `POST /instances/{id}/files/edit` | Edit a file | svc-filesystem |
| `POST /instances/{id}/files/grep` | Search file contents | svc-search |
| `POST /instances/{id}/files/glob` | Find files by pattern | svc-search |

### Backend Drivers

The machine service uses a driver interface to support multiple backends:

**SSH/SFTP** (primary driver):
- Works for local (`localhost:22`) and remote hosts identically
- File operations via SFTP
- Command execution via SSH exec channel
- One protocol for everything — gives full host access without Docker volume mounts

**S3** (future, deferred):
- File operations via S3 API
- No exec capability
- The driver interface must handle "this backend doesn't support exec" gracefully

### Service Discovery

With the consolidated machine service, the service discovery problem is dramatically simplified:

- Machine tools (`bash`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`) all map to the machine service's app-id in the routing table
- The orchestrator dispatches them through the routing table like any other tool — no special dispatch path
- The only new element: the orchestrator passes the session's `machine_instance_id` with each machine tool call
- Non-machine tools (`web_search`, `todo`, `skills`, `modes`, `delegation`) work through the routing table exactly as today
- No tool service ever needs to resolve another service's app-id — the inter-service routing problem is eliminated for the machine layer entirely

### Agent Definitions

Agent definitions no longer include bash, filesystem, or search as separate entries. Just `machine` (if the agent needs it):

**Agent with machine access**:
```yaml
agent:
  ref: foundation
  orchestrator:
    build: ./services/svc-orchestrator
  context_manager:
    build: ./services/svc-context
  providers:
    build: ./services/svc-providers
  behaviors:
    machine:
      build: ./services/svc-machine
    web:
      build: ./services/svc-web
    todo:
      build: ./services/svc-todo
    modes:
      build: ./services/svc-modes
    delegation:
      build: ./services/svc-delegation
    skills:
      build: ./services/svc-skills
```

**Agent without machine access**:
```yaml
agent:
  ref: research-only
  orchestrator:
    build: ./services/svc-orchestrator
  context_manager:
    build: ./services/svc-context
  providers:
    build: ./services/svc-providers
  behaviors:
    web:
      build: ./services/svc-web
    skills:
      build: ./services/svc-skills
```

## Data Flow

### Tool Dispatch

All tool calls go through the routing table, same as today:

```
routing_table.tools["bash"]        → svc-machine-6719a84c
routing_table.tools["read_file"]   → svc-machine-6719a84c
routing_table.tools["write_file"]  → svc-machine-6719a84c
routing_table.tools["edit_file"]   → svc-machine-6719a84c
routing_table.tools["grep"]        → svc-machine-6719a84c
routing_table.tools["glob"]        → svc-machine-6719a84c
routing_table.tools["web_search"]  → svc-web-cd2a2a7c
routing_table.tools["todo"]        → svc-todo-138c608f
```

Multiple tool names map to the same machine service app-id. The orchestrator doesn't need to know or care — it dispatches to whatever app-id the routing table says.

The turn payload from session-service includes `machine_instance_id`. The orchestrator includes it in the request body when dispatching tool calls. The machine service uses it; other tools ignore it.

The orchestrator remains stateless and agent-agnostic. No special dispatch paths.

### Session Lifecycle

1. **CLI sends create request**: `POST /sessions/create {agent: "foundation", machine: {type: "ssh", host: "localhost", working_dir: "/home/user/project"}}`
2. **Session-service resolves agent config**: Looks up the agent in agent definitions and service-map, gets the routing table (same as today)
3. **Session-service checks if agent has machine**: If the agent's behaviors include `machine`, session-service provisions a machine instance
4. **Session-service calls machine service**: `POST /v1.0/invoke/{machine_app_id}/method/instances` with the machine config from the CLI request. Machine service creates the instance (e.g., opens SSH connection to localhost), returns an instance ID
5. **Session-service records everything**: Session state now includes `session_id`, `agent_ref`, `routing_table`, and `machine_instance_id`
6. **During the session**: Each turn payload to the orchestrator includes `machine_instance_id`. The orchestrator passes it along with machine tool calls
7. **Session end**: Session-service calls `DELETE /v1.0/invoke/{machine_app_id}/method/instances/{id}` to clean up the machine instance

**If the agent has no machine**: Steps 3-4 are skipped. No `machine_instance_id` in session state. If the LLM tries to call bash/read_file/etc., the orchestrator won't find them in the routing table and returns a "tool not available" error. This is correct behavior — the agent doesn't have machine access.

**CLI changes**: The CLI now also sends machine configuration (type, host, working_dir). For the common local case, the CLI defaults to `{type: "ssh", host: "localhost", working_dir: pwd}`.

### Impact on `ampctl compose`

**What changes**:
- svc-bash, svc-filesystem, svc-search are eliminated from compose generation
- svc-machine stays as an agent-composed service with a hash-suffixed name
- Agent definitions that include `machine` get the consolidated service; those that don't simply lack filesystem/exec capabilities
- The service-map behaviors section no longer includes bash, filesystem, search as separate entries
- Machine appears as a single entry routing all machine tool names to one app-id

**What stays the same**:
- Framework services: session-service (fixed name), Redis, Dapr
- All other agent-composed services: hash-suffixed, deduplicated as today
- Service-map structure: machine appears in an agent's `behaviors` as a single entry

## Error Handling

- **Agent without machine access**: If the LLM calls a machine tool (bash, read_file, etc.) for an agent that doesn't include machine in its behaviors, the orchestrator won't find the tool in the routing table and returns a "tool not available" error
- **Machine instance creation failure**: If the machine service can't create an instance (e.g., SSH connection refused), session creation fails with a clear error propagated to the CLI
- **Machine instance cleanup on session end**: Session-service calls the delete endpoint. Abnormal termination cleanup is an open question (see below)
- **Backend doesn't support operation**: If an S3-backed instance receives an exec call, the machine service returns a "not supported by this backend" error

## Testing Strategy

- **Unit tests**: Machine service driver interface — SSH/SFTP driver correctly translates API calls to SSH/SFTP operations
- **Integration tests**: Session lifecycle — create session with machine, dispatch tool calls, verify instance creation and cleanup
- **Compose tests**: `ampctl compose` generates correct docker-compose.yaml without bash/filesystem/search services, with machine service routing all tool names
- **Routing table tests**: Verify multiple tool names correctly map to a single machine service app-id
- **Negative tests**: Agent without machine behavior rejects machine tool calls; session creation fails gracefully when SSH connection is refused

## Future Extension Points

**Display/GUI support** (deferred):
- The machine instance API is extensible. Display capabilities (screenshot, click, type, scroll) can be added as new endpoints on the instance without changing the architecture
- VNC and CDP would be additional backend drivers in the machine service
- A session needing display would include display configuration: `{type: "ssh", host: "localhost", display: {type: "vnc", port: 5900}}`
- The orchestrator wouldn't need to change — display tools would be additional tool names in the routing table, all pointing to the same machine service

**S3 backend** (deferred):
- Another backend driver. File ops only, no exec. The driver interface handles "this backend doesn't support exec" gracefully

## Open Questions

- **SSH key management**: How does the machine service get credentials? Environment variable? Secret store?
- **Abnormal termination cleanup**: Machine instance cleanup on abnormal session termination — timeout-based garbage collection?
- **Connection pooling**: Does each instance maintain a persistent SSH connection, or reconnect per-call?

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Machine is a composed service, not framework-level | Not every agent needs machine access |
| Bash, filesystem, search absorbed into machine | They were just proxies to machine anyway |
| SSH for local too (localhost:22) | One protocol for everything; full host access without Docker volume mounts |
| Per-session machine instances | Different sessions may connect to different hosts/workspaces |
| Machine instance ID passed per-turn | Keeps the orchestrator stateless |
| Display/GUI deferred | The design supports it as an extension but we don't know enough yet to design it properly |

## Invariants Preserved

1. All services are stateless (machine instances are managed state, not service state)
2. The orchestrator is agent-agnostic — receives everything per-turn via routing table + instance ID
3. Session-service is the routing authority
4. Agent definitions specify composed services; framework provides only session-service, Redis, Dapr
5. Hash-suffixed names for deduplication continue for all composed services
6. One machine instance per session
