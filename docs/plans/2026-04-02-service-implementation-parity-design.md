# Service Implementation Parity Design

## Goal

Bring all IPC services to feature parity with their upstream Amplifier modules, create missing services, and populate all content services with upstream bundle content — organized as feature-complete vertical slices around agent definitions.

## Background

The Amplifier IPC microservices system has all service scaffolding in place: service directories exist, Dapr sidecars are configured, basic endpoints respond, and the orchestrator loop runs. However, most services implement only the skeleton of their upstream counterparts. Tool services expose basic schemas but lack the full parameter sets. Hook services have placeholder logic. Content services reference bundles but don't serve all files. The delegation service can't actually spawn child sessions with proper context inheritance.

The result: the `foundation` agent definition in `agents/foundation.yaml` references ~25 services, but running a real session against it hits gaps everywhere. This design closes those gaps.

## Approach

**Feature-complete vertical slices** (bottom-up within each slice). Work is organized around agent definitions — make every service a given agent references fully functional with upstream feature parity. Within each slice, work proceeds bottom-up: execution layer first, then tools, then hooks, then content.

Why vertical slices over horizontal layers:
- A completed slice produces a working agent, not a half-working everything
- Dependencies flow downward (tools → machine, hooks → tools), so bottom-up avoids blocked work
- Each slice is independently testable end-to-end

## Architecture — The Three Slices

| Slice | Scope | Size |
|-------|-------|------|
| **Slice 1: Foundation Agent** | Every service referenced by `agents/foundation.yaml` | ~90% of work |
| **Slice 2: Default Agent** | Verify default agent works (shares most services via compose dedup) | ~5% — mostly verification |
| **Slice 3: New Services** | Services not yet in any agent definition: redaction, status-context, todo-reminder hooks | ~5% — implement and wire |

### Slice 1 Service Map

```
Execution Layer        Tool Services            Hook Services              Content Services
─────────────────     ──────────────────       ─────────────────────     ──────────────────────────
svc-machine ◄──────── svc-bash                 svc-hooks-approval        svc-content-amplifier ✓
  (safety, truncate,  svc-search               svc-hooks-routing         svc-content-core ✓
   background exec,   svc-filesystem           svc-hooks-async ✓         svc-content-foundation (NEW)
   rich grep/glob)    svc-web ✓                svc-hooks-shell ✓         svc-content-browser-tester
                       svc-skills                                         svc-content-design-intelligence
                       svc-todo                 Singleton Services         svc-content-filesystem
                       svc-modes ✓              ──────────────────        svc-content-recipes
                       svc-delegation           svc-orchestrator          svc-content-superpowers
                                                session-service
                                                svc-context

✓ = already at or near parity
```

---

## Slice 1: Foundation Agent

### 1.1 Execution Layer — svc-machine

svc-machine is the execution boundary. All tool services call it for shell execution, file operations, and search. Four gaps to close:

#### Safety Validation

Port `SafetyValidator` from upstream `tool-bash` into svc-machine. Profile-based system with three levels set via `SAFETY_PROFILE` environment variable:

| Profile | Behavior |
|---------|----------|
| `strict` | Deny destructive commands (`rm -rf /`, `sudo rm`, `mkfs`, etc.), deny network-modifying commands |
| `standard` | Deny obviously destructive commands, allow most development operations |
| `permissive` | Log warnings only, don't deny |

Safety lives in svc-machine (not svc-bash) because it's the actual execution layer — any service calling `/exec` gets safety enforcement regardless of which tool initiated the call.

#### Output Truncation

Port `_truncate_output()` logic. When output exceeds `MAX_OUTPUT_BYTES` (default 100KB):
- Show first N lines (head)
- Insert `[...truncated...]` marker with byte counts
- Show last M lines (tail)
- Return metadata: `truncated: true`, `total_bytes`, `shown_bytes`

#### Background Execution

Add `run_in_background` support to `/exec`. When true:
- Spawn process detached from request lifecycle
- Return immediately with `{"pid": <int>, "status": "running"}`
- Caller can poll via existing `/exec` with a status-check command

#### Grep and Glob Enrichment

Replace Python `re`-based grep with ripgrep (install `rg` in Dockerfile — no fallback needed since we control the image).

Enrich `/files/grep` endpoint to accept the full parameter set:

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `pattern` | string | (required) | Regex pattern |
| `path` | string | `.` | Search root |
| `output_mode` | enum | `files_with_matches` | `files_with_matches` / `content` / `count` |
| `glob` | string | — | File glob filter (`*.py`) |
| `type` | string | — | File type filter (`py`, `js`, `rust`) |
| `-A` | int | — | Lines after match |
| `-B` | int | — | Lines before match |
| `-C` | int | — | Lines around match |
| `-i` | bool | false | Case insensitive |
| `-n` | bool | true | Show line numbers |
| `head_limit` | int | mode-dependent | Max results |
| `offset` | int | 0 | Skip first N results |
| `include_ignored` | bool | false | Search excluded dirs |
| `multiline` | bool | false | Patterns span lines |

Enrich `/files/glob` endpoint:

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `pattern` | string | (required) | Glob pattern |
| `path` | string | `.` | Search root |
| `exclude` | list[string] | — | Patterns to exclude |
| `type` | enum | `file` | `file` / `dir` / `any` |
| `include_ignored` | bool | false | Search excluded dirs |

---

### 1.2 Tool Services — Feature Parity

#### svc-bash

- Add `run_in_background` parameter — forward to svc-machine's `/exec` with the flag
- Add output truncation config (`max_output_bytes`, default 100KB) — forward to svc-machine
- Add approval metadata to tool schema: `requires_approval: true`, `risk_level: "high"` — consumed by svc-hooks-approval for argument-level inspection

#### svc-search

Forward the full grep and glob parameter sets to svc-machine. Tool schemas must declare all parameters so the LLM can use them:

- **grep tool**: `pattern`, `path`, `output_mode`, `glob`, `type`, `-A/-B/-C`, `-i`, `-n`, `multiline`, `head_limit`, `offset`, `include_ignored`
- **glob tool**: `pattern`, `path`, `exclude`, `type`, `include_ignored`

#### svc-filesystem

- Add directory listing: when `file_path` is a directory, return `DIR/FILE` formatted listing instead of erroring
- Add `cat -n` line number formatting to file reads
- Add `max_line_length` truncation (2000 chars) — lines exceeding this get truncated with `...`
- Port richer tool descriptions from upstream (the descriptions guide the LLM's tool use)

#### svc-web

Already the most complete tool service. Verify against upstream — likely minimal or no work needed.

#### svc-skills

Basic list/search/info/load works. Two additions:

1. **Fork skill support** — Some skills specify `context: fork`, meaning they should run in a sub-session. When loading such a skill, svc-skills spawns a child session via svc-delegation instead of returning content inline.

2. **SkillsVisibilityHook** — A new hook endpoint within svc-skills that fires on `provider:request` (pre-hook). Reads available skills from the skill registry and injects them as a `<system-reminder source="hooks-skills-visibility">` block into the system context. This is how the LLM knows what skills are available.

#### svc-todo

The tool itself works. Two hook implementations needed:

1. **TodoReminderHook** — Pre-hook on `provider:request`. Reads session-keyed todo state from Dapr state store (key: `todo-{session_id}`) and injects as `<system-reminder source="hooks-todo-reminder">` before each LLM request. This keeps the LLM aware of pending tasks.

2. **TodoDisplayHook** — Post-hook that formats todo progress changes for streaming display in the CLI.

Session isolation: multiple concurrent sessions each get isolated todo state via session-keyed Dapr state store keys.

#### svc-modes

Already well-implemented. Verify against upstream — minimal gaps expected.

#### svc-delegation

Fundamental to multi-agent functionality. Full redesign of the tool interface and context inheritance flow.

**New tool schema** (replacing current 5-parameter version):

| Parameter | Type | Required | Default | Purpose |
|-----------|------|----------|---------|---------|
| `instruction` | string | yes | — | Task for child agent (renamed from `prompt`) |
| `agent` | string | no | `"self"` | Agent reference (e.g., `foundation:explorer`) |
| `session_id` | string | no | — | Resume existing child session |
| `context_depth` | enum | no | `"recent"` | `none` / `recent` / `all` |
| `context_scope` | enum | no | `"conversation"` | `conversation` / `agents` / `full` |
| `context_turns` | int | no | 5 | Number of turns when depth is `"recent"` |
| `model_role` | string | no | — | Override child's model role |
| `provider_preferences` | list | no | — | Ordered provider/model fallback list |

**Context inheritance flow:**
1. svc-delegation calls `GET /sessions/{parent_session_id}/messages` on session-service
2. Session-service filters the transcript by `context_scope` and `context_turns`
3. Filtered context is injected into the child session's initial payload
4. Child session-service assembles the child's system prompt from the resolved agent's content services

**Session resumption:** When `session_id` is provided, session-service checks for an existing transcript in Dapr state store and appends a new turn rather than starting fresh.

**Recursion guard:** `delegation_depth` counter is threaded through the request chain. Each delegation increments it. When it hits `MAX_DELEGATION_DEPTH` (default 10), svc-delegation returns an error instead of spawning.

**Agent resolution:** The `agent` parameter maps to `agent_ref` in the TurnRequest. Session-service calls `get_agent_config(agent_ref)` to load the target agent's full service configuration.

---

### 1.3 Hook Services

#### svc-hooks-approval (enrich)

Currently a glob-pattern deny-list. Enrich to support:

1. **Allow-list mode** — In addition to deny-list, support explicit allow-lists (only permitted tools can execute)
2. **Argument inspection** — For svc-bash tool calls, inspect the `command` string for dangerous patterns (not just the tool name). Pattern library ported from upstream.
3. **Risk metadata** — Read `requires_approval` and `risk_level` fields from tool call metadata that svc-bash now provides
4. **Structured denial** — Return DENY with a human-readable `reason` field explaining why a tool call was blocked

#### svc-hooks-routing (enrich)

Currently loads a YAML routing matrix and injects role names as text. Add real `resolve(model_role)` logic:

1. Given a role (e.g., `"fast"`, `"reasoning"`, `"coding"`), look up the routing matrix YAML
2. Find the specific provider + model combination for that role
3. Modify the provider request to target that provider and model
4. This is the mechanism that makes `model_role` in delegation and agent definitions functional

The routing matrix YAML format already exists in `related-projects/amplifier-bundle-routing-matrix/`.

#### svc-hooks-async (minimal)

Already well-implemented (Dapr pub/sub JSONL logging for 10 event topics). Only gap: add compaction and redaction event topics once those services exist in Slice 3.

#### svc-hooks-shell (done)

Already well-implemented (shell script bridge with exit-code semantics). No significant gaps.

---

### 1.4 Content Services

#### Remove svc-content-system-design-intelligence

No upstream bundle exists. This was created speculatively. Remove the service directory, remove from agent definitions.

#### Create svc-content-foundation (NEW)

The amplifier-foundation bundle has 20 context files and 16 agent definitions that aren't served by any content service today:

- **Context files**: delegation instructions, multi-agent patterns, implementation philosophy, awareness index, etc.
- **Agent definitions**: bug-hunter, explorer, zen-architect, git-ops, and 12 others

New service: `services/svc-content-foundation/` with standard content service structure (describe.yaml listing all files and agents, content files in a `context/` subdirectory).

#### Port content to existing services

| Service | Files to Port | Agent Declarations |
|---------|--------------|-------------------|
| `svc-content-amplifier` | ✓ Complete (3/3 files, 4 agents) | ✓ Done |
| `svc-content-core` | ✓ Complete (2/2 files, 4 agents) | ✓ Done |
| `svc-content-browser-tester` | 2 files (`browser-awareness.md`, `browser-guide.md`) | Already has 3 agents |
| `svc-content-design-intelligence` | 15 files (across `knowledge-base/`, `philosophy/`, `protocols/`) | 7 agents |
| `svc-content-filesystem` | 1 file (`editing-guidance.md`) | 0 agents |
| `svc-content-recipes` | 2 files (`recipe-awareness.md`, `recipe-instructions.md`) | 2 agents |
| `svc-content-superpowers` | 6 files (philosophy, TDD, debugging, etc.) | 5 agents |

Porting is mechanical: copy content files from upstream cache into each service's context directory, update `describe.yaml` to list them.

---

### 1.5 svc-context — Proper Compaction

The context manager works but is simplified. Four upgrades:

#### Session-Keyed Isolation

Currently single-instance in-memory. Add session ID to all operations:
- `GET /context/{session_id}/messages`
- `POST /context/{session_id}/messages`

Back storage with Dapr state store so context survives restarts. This parallels the svc-todo session-keying pattern.

#### 7-Level Compaction

The current 5-level compaction drops messages individually, which can break tool-call/result pairs. Port the upstream paired-removal logic: when removing a tool call, always remove its matching tool result (and vice versa). The 7 levels from upstream provide finer granularity for progressive context compaction.

#### Compaction Notices

When compaction occurs, generate a `<system-reminder source="context-compaction">` block that tells the LLM:
- What was removed (e.g., "3 tool call/result pairs from early in the conversation")
- How to recover (e.g., "re-run tools if you need full output")

This is critical for the LLM to not get confused by missing context mid-conversation.

#### System Prompt Factory

Add `POST /context/{session_id}/system-prompt` endpoint. Session-service calls this to set the system prompt. The system prompt is assembled by session-service from content services and agent instructions, but the context manager owns injecting it into the message list. This separates "what the system prompt says" (session-service's concern) from "where it goes in the message list" (context manager's concern).

---

### 1.6 Singleton Service Updates

#### svc-orchestrator

Already has the full agent loop with streaming, tool dispatch, hook dispatch, and child session spawning. One change: support the enriched delegation flow from Section 1.2. The `/orchestrator/delegate` endpoint needs to:

- Accept the new delegation parameters (`agent`, `context_depth`, `context_scope`, `model_role`, etc.)
- Forward them through `ChildSessionSpawner` to session-service
- Thread the `delegation_depth` counter through the request chain

#### session-service

Two additive changes (existing endpoints don't change):

1. **`GET /sessions/{session_id}/messages`** — Return the session transcript so svc-delegation can extract context for child sessions
2. **Dapr state store persistence** — Persist session transcripts to Dapr state store (currently in-memory `_sessions` dict) so they survive restarts and support session resumption

---

### 1.7 Agent Definition and Compose Updates

After all services are implemented, update `agents/foundation.yaml`:
- **Add**: `svc-hooks-redaction`, `svc-hooks-status-context`, `svc-hooks-todo-reminder`
- **Remove**: `content-system-design-intelligence`
- **Add**: `content-foundation`

Then regenerate `docker-compose.yaml` via `ampctl compose`.

---

## Slice 2: Default Agent

After Slice 1, verify the default agent works end-to-end. Since it shares most services with foundation via compose dedup, this is primarily verification plus any default-specific content adjustments. The default agent uses a subset of foundation's services, so if foundation works, default should work with minimal additional effort.

---

## Slice 3: New Hook Services

Three new hook services that get added to agent definitions and implemented:

### svc-hooks-redaction (NEW)

Pre-hook that masks secrets and PII in event payloads before they hit logging or the LLM. Port from upstream `amplifier-module-hooks-redaction`.

- Fires on **all events** (universal pre-hook)
- Regex-based matching for: AWS access keys, JWT tokens, API tokens/keys, email addresses, private keys
- Structural field allowlists to avoid false positives on known-safe fields
- Replacement format: `[REDACTED:type]` (e.g., `[REDACTED:aws-key]`)

### svc-hooks-status-context (NEW)

Pre-hook on `provider:request` that injects environmental context into the system prompt.

- Port from upstream `amplifier-module-hooks-status-context`
- Calls svc-machine for: git status, git branch, platform info, working directory
- Adds: current datetime, session metadata
- Injected as `<system-reminder source="hooks-status-context">` block

### svc-hooks-todo-reminder (NEW)

Pre-hook on `provider:request` that injects current todo state.

- Reads session-keyed todo state from Dapr state store (key: `todo-{session_id}`)
- Formats as `<system-reminder source="hooks-todo-reminder">` block
- Only injects when todo list is non-empty
- Port from upstream `amplifier-module-hooks-todo-reminder`

---

## Data Flow

### Tool Execution Flow (svc-bash example)

```
LLM → orchestrator → svc-hooks-approval (pre-hook, checks risk metadata)
                    → svc-bash (tool invocation)
                        → svc-machine /exec (safety validation, execution, truncation)
                    → svc-hooks-async (post-hook, logs event)
                    → response back to LLM
```

### Delegation Flow

```
LLM calls delegate tool
  → svc-delegation receives (instruction, agent, context_depth, ...)
  → svc-delegation calls GET /sessions/{parent_id}/messages on session-service
  → svc-delegation calls POST /orchestrator/delegate with:
      - child instruction + filtered parent context
      - agent_ref for agent resolution
      - delegation_depth + 1
  → orchestrator spawns child session via session-service
  → session-service resolves agent config, assembles system prompt from content services
  → child session runs to completion
  → result returned to parent delegation tool call
```

### Context Compaction Flow

```
New message arrives at svc-context
  → Check token count against threshold
  → If over: apply compaction level N
      → Remove paired tool-call/result (never orphan one side)
      → Generate compaction notice
      → Increment to level N+1 if still over
  → Store updated context in Dapr state store
```

---

## Error Handling

- **svc-machine safety denial**: Return 403 with `{"denied": true, "reason": "..."}`. Tool service translates to a tool error the LLM can understand.
- **Delegation depth exceeded**: svc-delegation returns tool error: "Maximum delegation depth (10) reached. Cannot spawn further child sessions."
- **Hook failures**: Non-blocking by default. If a pre-hook fails, log the error and continue (don't block the tool call). Exception: svc-hooks-approval denial is blocking.
- **Content service unavailable**: Session-service logs a warning and assembles the system prompt without that content. The agent still works, just with reduced context.
- **Context compaction**: Never loses the system prompt or the most recent turn. Compaction operates on middle history only.

---

## Testing Strategy

Each service is tested at three levels:

1. **Unit tests** — Within each service directory (`uv run pytest tests/`). Test business logic: safety validator patterns, compaction paired-removal, context filtering, parameter forwarding.

2. **Integration tests** — Bring up the full stack via `docker-compose up`. Run a real turn through the CLI targeting the foundation agent. Verify:
   - All tools respond with correct schemas
   - Hooks fire in correct order (check async logs)
   - Content is served (check system prompt assembly)
   - Delegation spawns a child session and returns results

3. **Agent smoke test** — Run a multi-turn conversation with the foundation agent that exercises: file reading, bash execution, search, todo tracking, delegation to a sub-agent, and skill loading. This is the "it actually works" test.

---

## Open Questions

1. **Should svc-hooks-todo-reminder be a separate service or folded into svc-todo?** Current design: separate, because hooks and tools have different triggering semantics in Dapr — tools respond to invocations, hooks subscribe to pub/sub events. Mixing both patterns in one service adds complexity.

2. **Should we support hot-reload of routing matrix YAML or require service restart?** Hot-reload is nicer for development but adds file-watching complexity. Proposal: start with restart-required, add hot-reload later if painful.

3. **What's the right max delegation depth default?** Proposed: 10. Deep enough for legitimate multi-agent workflows, shallow enough to catch infinite loops quickly.