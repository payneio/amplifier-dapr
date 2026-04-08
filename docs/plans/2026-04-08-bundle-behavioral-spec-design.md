# Bundle Behavioral Specification Recipe Design

## Goal

A recipe that takes a resolved Amplifier bundle name, analyzes its full transitive composition from the registry cache, and produces a document describing the expected behavioral logic -- reverse-engineering the "program" the bundle encodes for the LLM.

## Background

Amplifier bundles compose behaviors, modes, agents, skills, recipes, and context files into a layered system that shapes LLM behavior. Understanding what a fully-resolved bundle actually *does* requires tracing its entire transitive dependency tree, reading every component, and synthesizing the cross-cutting behavioral contracts into a coherent specification.

This is currently a manual, error-prone process. The bundle YAML files are highly structural, but the behavioral logic is scattered across markdown prose (mode instructions, agent definitions, skill guides, context files) that only makes sense when read together. No single file explains "when a user asks to build a feature, what happens end-to-end."

This recipe automates that analysis, producing a scenario-driven behavioral specification that reads like a program description -- making the implicit behavioral contracts explicit and auditable.

## Approach

**Two-Pass Architecture: Parse + LLM Extract + Synthesize**

The recipe uses deterministic YAML parsing for structural data and LLM extraction only for prose content, then synthesizes everything into a scenario-driven behavioral specification. This approach was chosen because:

1. **Most bundle data is machine-parseable.** Behavior YAMLs, recipe step graphs, mode frontmatter, and tool configurations are fully deterministic. Using LLM calls for these would be wasteful and less reliable.
2. **Prose content requires semantic understanding.** Context files, agent bodies, and skill guides contain behavioral directives, workflow phases, and delegation contracts that only an LLM can extract meaningfully.
3. **Synthesis requires cross-file reasoning.** The final behavioral specification emerges from contracts *between* components (e.g., a mode's delegation instruction references an agent that references a skill). This requires a reasoning-capable agent with full context.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Recipe Executor                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Step 1a: Deterministic Parse                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │ registry.json → dependency tree → YAML parse      │  │
│  │ → @mention extraction → ParsedManifest per file   │  │
│  │ → triage: flag prose-heavy files for LLM          │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│  Step 1b: LLM Extraction (parallel: 5)                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │ foreach prose-heavy file:                         │  │
│  │   → 6-field focused extraction                    │  │
│  │   → purpose, directives, triggers, exits,         │  │
│  │     references, phases                            │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                              │
│                          ▼                              │
│  Step 2: Synthesis (reasoning agent)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │ All ParsedManifests + All LLM Extractions         │  │
│  │ → cross-file contract discovery                   │  │
│  │ → transition graph interpretation                 │  │
│  │ → composition-order awareness                     │  │
│  │ → scenario-driven behavioral spec document        │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Components

### Step 1a: Deterministic Parse

A single agent with filesystem and Python tools performs all structural extraction:

1. **Registry walk.** Read `~/.amplifier/registry.json`, starting from the target bundle name. Recursively walk the `includes` field to build the full dependency tree.

2. **YAML parse.** For each resolved bundle, parse the actual YAML file to extract: tools (with configs, especially tool-skills sources), context.include files, agents.include, hooks, providers, spawn policy.

3. **@mention extraction.** Extract @mentions recursively from all .md files using regex: `@([a-zA-Z0-9_][a-zA-Z0-9_.-]*):([a-zA-Z0-9_./-]+)`.

4. **Skills discovery.** Map tool-skills config URIs to cache paths for precise skills discovery. Also scan `~/.amplifier/cache/skills/` for cached skills collections.

5. **Settings overlay.** Read `~/.amplifier/settings.yaml` for runtime overrides.

6. **Component file discovery.** Within each resolved cache path, find all component files: `modes/`, `recipes/`, `agents/`, `context/`, and the bundle/behavior YAML files.

7. **Typed manifest production.** For each file, produce a typed `ParsedManifest` with structural data (see schema below).

8. **Triage.** Flag which files have prose content needing LLM extraction based on the file type heuristic.

#### File Type Triage Heuristic

Validated against real files in the Amplifier ecosystem:

| Type | YAML Parseable | LLM Needed | Notes |
|------|----------------|------------|-------|
| Behavior YAML | ~85% | Skip LLM | Pure config, description field suffices |
| Recipe YAML | ~70% structural | Step prompt summaries only | Step graph fully parseable |
| Mode .md | ~65% (frontmatter) | ~35% (body has phases, methodology) | Both layers needed |
| Agent .md | ~25% | ~75% (meta.description triggers, body methodology) | Heavy LLM |
| Skill SKILL.md | ~15% | ~85% (phases, tables, behavioral logic in body) | Heavy LLM |
| Context .md | ~0% | ~100% (no frontmatter, pure prose behavioral shaping) | Heaviest LLM |

### Step 1b: LLM Extraction

For each file flagged by the triage step, one LLM call with a focused 6-field extraction schema.

- Uses `foreach` with `parallel: 5` to run extractions concurrently
- Behavior YAMLs are skipped entirely (deterministic parse suffices)
- Recipes optionally deferred (step-level summaries can wait for synthesis)

### Step 2: Synthesis

A reasoning-role agent receives all ParsedManifests and LLM extractions, then performs:

1. **Cross-file contract discovery.** E.g., `delegation-instructions.md` says "delegate to bug-hunter" + debug mode says "delegate Phase 4 to bug-hunter" + `bug-hunter.md` says "I do TDD debugging."

2. **Transition graph interpretation.** Modes form directed workflow graphs; the agent maps out the full state machine.

3. **Composition-order awareness.** Determines which instruction "wins" -- later overrides earlier in includes.

4. **Context loading classification.** Distinguishes always-loaded vs on-demand context.

5. **Document production.** Produces the scenario-driven behavioral specification document directly (no separate "writing" step).

## Data Structures

### ParsedManifest Schema

Deterministic, produced per file:

```
ParsedManifest (all types):
  file_path: string
  component_type: "mode" | "agent" | "recipe" | "skill" | "behavior_yaml" | "context_file"
  bundle_origin: string
  description: string | null          (from YAML description field)
  eager_mentions: list[string]         (regex-extracted @namespace:path from body)

  if mode:
    name, shortcut
    tool_categories: {safe: [...], warn: [...], confirm: [...]}
    default_action: "block" | "allow"
    allowed_transitions: list[string]
    allow_clear: bool

  if agent:
    name
    meta_description_raw: string       (full text, unparsed)
    model_role: list[string]
    tool_modules: list[{module, source}]

  if recipe:
    name, version, tags
    execution_mode: "flat" | "staged"
    input_interface: {required: [...], optional: [...]}
    steps: list[{id, type, agent, condition, output, foreach, parallel}]
    data_flow: {variable: {produced_by, consumed_by: [...]}}
    approval_gates: list[{stage, requires_approval, approval_context_template}]
    sub_recipe_calls: list[{step_id, recipe_path}]

  if skill:
    name
    context_mode: "fork" | null
    disable_model_invocation: bool
    user_invocable: bool
    model_role: string | null

  if behavior_yaml:
    name
    tool_modules: list[{module, source, config_summary}]
    hook_modules: list[{module, source, config_summary}]
    context_includes: list[string]
    agent_includes: list[string]
    nested_behavior_includes: list[string]

  if context_file:
    (just base fields -- no frontmatter to parse)
```

### LLM Extraction Schema

Six fields, produced per prose-heavy file:

```json
{
  "file_path": "...",
  "component_type": "mode",

  "purpose": "One-sentence description of what this component does",

  "behavioral_directives": [
    "List of things this component tells the LLM to do or not do"
  ],

  "trigger_conditions": [
    "When this component activates or should be used"
  ],

  "exit_conditions": [
    "When this component finishes or transitions"
  ],

  "prose_references": [
    {"type": "delegation|skill|mode|recipe|tool", "target": "name", "when": "condition"}
  ],

  "workflow_phases": [
    "Ordered phases or steps described in the prose"
  ]
}
```

## Data Flow

```
registry.json + settings.yaml
        │
        ▼
  [Step 1a: Deterministic Parse]
        │
        ├──→ ParsedManifest[] (all files)
        │
        └──→ triaged file list (prose-heavy subset)
                    │
                    ▼
              [Step 1b: LLM Extraction]  (parallel: 5)
                    │
                    └──→ LLMExtraction[] (prose-heavy files only)
                                │
                                ▼
                    ┌───────────────────────┐
                    │    Step 2: Synthesis   │
                    │                       │
                    │  ParsedManifest[]     │
                    │  + LLMExtraction[]    │
                    │  → behavioral spec    │
                    └───────────────────────┘
                                │
                                ▼
                        output .md file
```

## Output Document Format

The recipe produces a single markdown document with three parts:

### Part 1: Component Inventory

Flat reference tables generated from parsed manifests:

- **Bundles** -- with includes chain
- **Modes** -- with shortcuts, default action, transitions
- **Agents** -- with model role, trigger summary
- **Skills** -- with context mode, invocable flag
- **Recipes** -- with execution mode, step count, gates

### Part 2: Relationship Graph

- **Mode transition state machine** (textual)
- **Delegation map** (which agents, when)
- **Context loading chain** (always-loaded vs mode-activated vs on-demand)

### Part 3: Expected Behavioral Logic (Scenarios)

Organized by user intent, not by mechanism type. Each scenario has: entry conditions, expected sequence with numbered steps. Each step shows: mechanism used (mode/skill/agent/recipe), tool restrictions, expected behavior, exit conditions. Decision points call out branching.

Example scenario structure:

```
SCENARIO: "User wants to build a new feature"
  ENTRY: User says "build X", "add Y", requests new work
  EXPECTED: Assistant recommends /brainstorm mode

  1. BRAINSTORM MODE
     ACTIVATED BY: mode(set, "brainstorm")
     SKILL LOADED: brainstorming
     TOOL RESTRICTIONS: write_file BLOCKED, edit_file BLOCKED, bash WARN
     EXPECTED SEQUENCE:
       a. Explore project context
       b. Ask questions one at a time, multiple choice preferred
       c. Propose 2-3 approaches with tradeoffs
       d. Present design in sections, validate each
       e. DELEGATE to superpowers:brainstormer
       f. Spec self-review
       g. User review gate
     EXIT: Design doc saved, user approves
     TRANSITIONS TO: write-plan

  2. WRITE-PLAN MODE
     ...

  DECISION POINTS:
    - Task < 20 lines: skip modes entirely
    - User declines brainstorm: skip to write-plan
    - Bug during execution: transition to debug
```

## Error Handling

| Scenario | Handling |
|----------|----------|
| Registry bundle with `local_path: null` (never fetched) | Skip gracefully, note in output as unresolvable |
| File too large for single LLM extraction | Split by section headers, extract per-section |
| Synthesis context exceeds model window | Pre-filter low-signal extractions (behavior YAML descriptions, context files with < 3 directives) |
| YAML parse failure on malformed file | Log warning, include file in output as "unparseable", continue |
| LLM extraction returns incomplete schema | Use partial results, flag missing fields in synthesis input |
| Circular includes in dependency tree | Track visited set, break cycle, warn in output |

## Testing Strategy

**Unit testing:**
- Registry walker: mock `registry.json` with known dependency trees, verify transitive resolution
- YAML parser: test against real bundle/behavior YAML files from the cache
- @mention regex: test against known files with various mention patterns
- Triage logic: verify correct file type classification

**Integration testing:**
- Run Step 1a against a real `foundation` bundle, verify ParsedManifest count and types match expected (~124 files)
- Run Step 1b on a small subset (3-5 files per type), verify extraction schema completeness
- Run full recipe against `foundation`, verify output document has all three parts

**Validation:**
- Manual review of output document against known bundle behavior
- Spot-check scenarios against actual session traces
- Compare component inventory tables against `ampctl` bundle inspection output

## Invocation

**Location:** `recipes/bundle-behavioral-spec.yaml` in the current project (local first, movable to bundle later)

```python
recipes(
    operation="execute",
    recipe_path="recipes/bundle-behavioral-spec.yaml",
    context={
        "bundle_name": "foundation",
        "registry_path": "~/.amplifier/registry.json",
        "output_path": "docs/bundle-behavioral-spec-foundation.md"
    }
)
```

## Expected Scale (foundation bundle)

| Metric | Estimate |
|--------|----------|
| Bundles/behaviors in dependency tree | ~20 |
| Modes | ~6 |
| Agents | ~25 |
| Recipes | ~8 |
| Skills | ~15 |
| Context files | ~20 |
| Behavior YAMLs | ~30 |
| Files needing LLM extraction | ~70 (behavior YAMLs skipped) |
| Output document size | 2,000-4,000 lines |

## Execution Model

- **Step 1a** is deterministic: one agent with filesystem + Python tools
- **Step 1b** uses `foreach` with `parallel: 5` for concurrent LLM extraction
- **Step 2** is a single reasoning-role agent call

## Known Limitations (v1)

- **Skills cache noise.** The skills cache may include collections from other compositions (accepted noise for v1).
- **Non-deterministic output.** Two runs produce different documents due to LLM extraction and synthesis variance.
- **No incremental updates.** Full re-run required to regenerate; no diffing against previous output.
- **No session trace comparison.** Cannot validate against actual session traces (future work).
- **No diagram generation.** Text-only output; no Mermaid or DOT diagrams.
- **Soft reference gaps.** References using `namespace:path` without the `@` prefix may be missed in prose scanning.

## Open Questions

None -- design is fully validated.