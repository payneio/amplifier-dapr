# Agent Definition System and Management CLI (ampctl) Design

## Goal

Replace the old IPC definition system (UUIDs, behavior files, discover/register/install lifecycle) with a single agent definition format and a management CLI (`ampctl`) that generates docker-compose infrastructure from definitions.

## Background

In the old IPC system, definitions carried both composition logic AND deployment instructions (stack, source, command). In the Dapr microservices world, deployment is handled by docker-compose.yaml. The IPC system also required separate behavior definition files for each service, which proved to be a maintenance burden -- an exhaustive review found that external behavior files had diverged from internal implementation files on 14 values, and 10 of 25 behaviors were pure service pointers with zero config (100% redundant).

We need a clean separation where:

- **Agent definition files** describe WHAT to compose (which services, what config)
- **docker-compose.yaml** describes HOW to run it (containers, images, ports)
- **A management CLI** bridges the two

This design eliminates behavior definition files entirely. Agent definitions are the only composition unit. Docker-compose.yaml is a generated artifact.

## Approach

The agent definition is the ONLY definition file type. Services self-report their capabilities via `/describe` at runtime -- the boolean capability flags that behavior files carried are redundant. Config defaults live in the service itself; overrides go in the agent definition. The image/build URI in the agent definition IS the service pointer. There is nothing left for a behavior definition file to do.

A separate management CLI (`ampctl`) handles the infrastructure side: fetching agent definitions, validating them, generating docker-compose.yaml, and managing the local agent cache. The session CLI (`amplifier-svc`) is unchanged -- it just uses whatever agents are installed.

## Architecture

```
                                ampctl
                               (manages)
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
   Agent Definitions       Service Map            docker-compose.yaml
   ~/.amplifier/agents/    ~/.amplifier/           (generated)
   ├── foundation.yaml     service-map.yaml
   └── my-agent.yaml
          │                                              │
          │              amplifier-svc                    │
          │             (session CLI)                     │
          │                  │                            │
          │       reads definitions                docker compose up
          │       + service map                          │
          └──────────┤                                   │
                     ▼                                   ▼
              Session Service ◄──── Dapr ────► Service Containers
```

Three artifacts, three concerns:

1. **Agent definition YAML** -- Declares what services compose an agent, with config overrides
2. **Service map** (`~/.amplifier/service-map.yaml`) -- Maps behavior keys to generated Dapr app-ids
3. **docker-compose.yaml** -- Generated infrastructure; containers, images, sidecars

## Components

### Agent Definition Format

The agent definition carries everything needed to describe an agent:

| Field | Purpose |
|---|---|
| `ref` | Agent identifier |
| `description` | Human-readable summary |
| `instruction` | System prompt seed for the LLM |
| `orchestrator` | Singleton: the agent loop driver |
| `context_manager` | Singleton: conversation context |
| `providers` | Singleton: all LLM providers in one container |
| `behaviors` | Map of capability services with optional config |

#### Full Example

```yaml
agent:
  ref: foundation
  description: Full-featured foundation agent
  instruction: |
    You are Amplifier, an AI-powered CLI tool that helps users accomplish
    tasks. You have access to tools for file operations, web search, code
    execution, and more. Focus on being helpful, accurate, and efficient.

  orchestrator:
    image: ghcr.io/payneio/amplifier-svc-orchestrator:latest

  context_manager:
    image: ghcr.io/payneio/amplifier-svc-context:latest

  providers:
    image: ghcr.io/payneio/amplifier-svc-providers:latest
    environment:
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
      OPENAI_API_KEY: "${OPENAI_API_KEY:-}"

  behaviors:
    bash:
      image: ghcr.io/payneio/amplifier-svc-bash:latest
    filesystem:
      image: ghcr.io/payneio/amplifier-svc-filesystem:latest
    search:
      image: ghcr.io/payneio/amplifier-svc-search:latest
    web:
      image: ghcr.io/payneio/amplifier-svc-web:latest
    machine:
      image: ghcr.io/payneio/amplifier-svc-machine:latest
      volumes:
        - "${WORKSPACE_PATH:-.}:/workspace"
    skills:
      image: ghcr.io/payneio/amplifier-svc-skills:latest
      config:
        visibility: full
    todo:
      image: ghcr.io/payneio/amplifier-svc-todo:latest
    modes:
      image: ghcr.io/payneio/amplifier-svc-modes:latest
    routing:
      image: ghcr.io/payneio/amplifier-svc-routing:latest
      config:
        default_matrix: balanced
    logging:
      image: ghcr.io/payneio/amplifier-svc-logging:latest
    redaction:
      image: ghcr.io/payneio/amplifier-svc-redaction:latest
      config:
        allowlist: [session_id, turn_id]
    content-core:
      image: ghcr.io/payneio/amplifier-svc-content-core:latest
    content-amplifier:
      image: ghcr.io/payneio/amplifier-svc-content-amplifier:latest

    # Local development -- Dockerfile (short form)
    my-custom-tool:
      build: ./services/my-custom-tool

    # Local development -- Dockerfile (long form)
    experimental-hook:
      build:
        context: ../experiments
        dockerfile: hooks/Dockerfile
      config:
        log_level: debug
```

#### Key Design Decisions

- **No UUIDs.** Docker-compose service naming conflicts are resolved via deterministic hashing of image/build values during compose generation.
- **No separate behavior definition files.** Services self-report capabilities via `/describe`. Config that varies per-agent is an override in the agent definition.
- **`image:` for registry images, `build:` for local development.** Standard docker-compose semantics.
- **Behavior keys are local labels**, not global identities. `bash`, `filesystem`, etc. are human-readable names within this definition only.
- **Deduplication.** The same image referenced by multiple agents generates only one docker-compose entry.
- **Multiple configurations of one image.** List the same image under different behavior keys with different `config` values (e.g., `skills` with `visibility: full` in one agent, `visibility: minimal` in another).
- **`providers` is singular and plural.** One container runs all available LLM providers. The session CLI's `--provider` flag selects which one at runtime.
- **`instruction` is the system prompt seed.** Combined with service content and workspace content at session start.

### Management CLI (ampctl)

A separate binary from the session CLI (`amplifier-svc`). Handles the infrastructure side.

#### Commands

```bash
# Add an agent definition with a local name
ampctl add <uri> <name>
# e.g.: ampctl add https://github.com/payneio/amplifier-agents/foundation.yaml foundation
# e.g.: ampctl add ./my-agents/custom.yaml my-agent
# Errors if name already exists:
#   "Error: agent 'foundation' already exists. Use 'ampctl remove foundation' first."

# List installed agents
ampctl list

# Remove an agent and clean up unused docker-compose entries
ampctl remove <name>

# Update an agent (re-fetch and regenerate)
ampctl update <name>

# Regenerate docker-compose.yaml from all installed definitions
ampctl compose

# Show what services an agent requires
ampctl inspect <name>
```

#### What `ampctl add` Does

1. Fetches the agent definition YAML from the URI (supports HTTPS, file paths)
2. Validates the YAML structure
3. Caches it locally at `~/.amplifier/agents/<name>.yaml`
4. For each service (orchestrator, context_manager, providers, all behaviors):
   - Generates a deterministic docker-compose service name by hashing the image URI or build path
   - Generates a docker-compose service entry (image or build, environment, volumes, depends_on)
   - Generates a Dapr sidecar entry (--app-id = the hashed service name)
   - Deduplication: if the same image is already in docker-compose from another agent, reuses the existing entry
5. Writes the generated entries to docker-compose.yaml (or a docker-compose.generated.yaml)
6. Maintains a mapping file (`~/.amplifier/service-map.yaml`) recording behavior-key → generated-app-id for each agent
7. Prints: `Run docker compose up -d to start new services`

#### Conflict Resolution via Hashing

The docker-compose service name is generated deterministically from the image/build value:

- Same image from two agents → same hash → same container (shared, no conflict)
- Different image for same behavior name → different hash → different containers (no conflict)
- No UUIDs needed. The image URI IS the unique identity.

## Data Flow

### Session Start (amplifier-svc run --agent foundation)

1. Session-service loads the cached agent definition from `~/.amplifier/agents/foundation.yaml`
2. Reads `~/.amplifier/service-map.yaml` to resolve behavior keys to Dapr app-ids
3. Calls `GET /describe` on each service (by its Dapr app-id) to discover capabilities
4. Builds the routing table from describe responses
5. Fetches content from content services
6. Assembles the system prompt: `agent.instruction` + service content + workspace content
7. Invokes the orchestrator with the routing table and system prompt
8. Config overrides from the agent definition are passed to services via the configure step or included in the orchestrator payload

### Local Development Workflow

For developing services locally:

1. Use `build:` instead of `image:` in the agent definition
2. `ampctl` generates a docker-compose entry with build context
3. `docker compose up --build` rebuilds from local source
4. Fast iteration without publishing to a registry

```yaml
behaviors:
  my-custom-tool:
    build: ./services/my-custom-tool
    config:
      debug: true
```

## Why No Behavior Definition Files

In the old IPC system, behavior definitions served three purposes:

1. **Composition** -- Declaring what capabilities a behavior provides (`tools: true`, `hooks: true`)
2. **Config** -- Setting default config for components
3. **Service pointer** -- Declaring how to install/run the backing service

In the Dapr world, all three are handled elsewhere:

1. **Composition** -- Services self-report via `/describe`. The boolean flags are redundant.
2. **Config** -- Defaults live in the service itself. Overrides go in the agent definition.
3. **Service pointer** -- The `image`/`build` in the agent definition IS the service pointer.

The exhaustive review of old IPC behavior definitions confirmed this:

- 10 of 25 behaviors were pure service pointers with zero config (100% redundant)
- Several had config values that were obvious service defaults
- External behavior files had diverged from internal implementation files on 14 values -- they weren't being maintained accurately
- The only irreducible information was: which services to compose (agent's job), which config to override (agent's job), and service identity (image URI's job)

## Relationship to the Existing System

### What This Replaces

| Old | New |
|---|---|
| `services/session-service/src/session_service/agents.py` (hardcoded agent registry) | Agent definition YAML files |
| Flat `DEFAULT_SERVICES` list | Per-agent service composition from definitions |
| Manual docker-compose.yaml editing | `ampctl`-managed generation |
| Behavior definition files | Eliminated entirely |
| UUID-based service identity | Deterministic hashing of image/build URIs |

### What This Does NOT Change

- The `/describe` endpoint contract on services
- The routing table construction in `discovery.py`
- The orchestrator's agent loop
- The session CLI (`amplifier-svc`)
- How services communicate via Dapr

## Error Handling

- **`ampctl add` with existing name** -- Error with message: `"Error: agent '<name>' already exists. Use 'ampctl remove <name>' first."`
- **Invalid YAML structure** -- `ampctl add` validates before caching. Rejects with specific error on malformed definitions.
- **Unreachable URI** -- `ampctl add` reports fetch failure. No partial state written.
- **Hash collisions** -- Astronomically unlikely with SHA-256. If encountered, append a disambiguator.
- **Missing services at session start** -- Session-service reports which services from the agent definition are unreachable, allowing partial degradation or fail-fast depending on service criticality.

## Testing Strategy

- **YAML validation tests** -- Verify that `ampctl` correctly validates well-formed and malformed agent definitions
- **Compose generation tests** -- Given agent definition(s), assert the generated docker-compose.yaml has correct service entries, sidecar config, and deduplication
- **Hash determinism tests** -- Same image URI always produces the same service name; different URIs produce different names
- **Service map tests** -- Verify behavior-key → app-id mappings are correctly written and read
- **Integration tests** -- `ampctl add` → `docker compose up` → `amplifier-svc run --agent <name>` → session completes successfully
- **Conflict/dedup tests** -- Two agents sharing the same image produce one docker-compose entry; removing one agent doesn't break the other

## Open Questions

1. **Generated compose file strategy** -- Should `ampctl` directly edit docker-compose.yaml, or generate a separate docker-compose.generated.yaml that the main compose file includes? Including is safer -- doesn't risk corrupting user edits.

2. **Human-readable hashed names** -- Should docker-compose service names be human-readable (e.g., `svc-bash-a3f2b1c4`) or pure hashes? Human-readable is better for debugging.

3. **Environment variable resolution** -- How should environment variables in agent definitions (like `${ANTHROPIC_API_KEY}`) be resolved? Docker Compose already handles env var substitution -- we can pass through.

4. **Agent inheritance/extension** -- Should `ampctl` support one agent extending another? Deferred -- YAGNI.

5. **Agent discovery by session-service** -- How should the session-service discover which agents are available? Read `~/.amplifier/agents/` directory? A separate manifest?