# Phase 4: Content Services & Agent Wiring Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Populate all content services with upstream bundle content, create the new svc-content-foundation service, remove the speculative svc-content-system-design-intelligence, and update agent definitions + compose to wire everything together.

**Architecture:** Content services are zero-code containers that use the SDK's `amplifier-serve` CLI. Each service has a `describe.yaml` (declaring content paths and agent definitions), a `content/` directory (holding the actual files), and a Dockerfile that copies both and runs `amplifier-serve --config /app/describe.yaml`. No custom Python code is needed. Content is ported verbatim from upstream sources in `related-projects/` and `~/.amplifier/cache/`.

**Tech Stack:** YAML, Markdown, Docker, `amplifier-serve` CLI (from amplifier-service-sdk), `ampctl compose`

---

### Task 1: Create svc-content-foundation — directory scaffold

**Files:**
- Create: `services/svc-content-foundation/Dockerfile`
- Create: `services/svc-content-foundation/content/.gitkeep` (temporary placeholder)

**Step 1: Create the service directory and Dockerfile**

Create `services/svc-content-foundation/Dockerfile`:

```dockerfile
# ── Stage 1: Shared Amplifier service base ────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-content-foundation ───────────────────────────────────────
FROM amplifier-service-base

COPY services/svc-content-foundation/describe.yaml /app/describe.yaml
COPY services/svc-content-foundation/content/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
```

**Step 2: Create placeholder content directory**

```bash
mkdir -p services/svc-content-foundation/content
touch services/svc-content-foundation/content/.gitkeep
```

**Step 3: Verify directory structure**

Run: `find services/svc-content-foundation/ -type f | sort`

Expected:
```
services/svc-content-foundation/Dockerfile
services/svc-content-foundation/content/.gitkeep
```

---

### Task 2: Create svc-content-foundation — copy content files

**Files:**
- Create: 20 files under `services/svc-content-foundation/content/`

The upstream content lives at `related-projects/amplifier-foundation/context/` with this structure:

```
context/
├── CONTEXT_POISONING.md
├── IMPLEMENTATION_PHILOSOPHY.md
├── ISSUE_HANDLING.md
├── KERNEL_PHILOSOPHY.md
├── LANGUAGE_PHILOSOPHY.md
├── MODULAR_DESIGN_PHILOSOPHY.md
├── POLYGLOT_BUNDLES.md
├── amplifier-shadow-tests.md
├── bundle-awareness.md
├── shared/
│   ├── AWARENESS_INDEX.md
│   ├── PROBLEM_SOLVING_PHILOSOPHY.md
│   ├── common-agent-base.md
│   └── common-system-base.md
├── agents/
│   ├── delegation-instructions.md
│   ├── multi-agent-patterns.md
│   ├── session-repair-knowledge.md
│   └── session-storage-knowledge.md
└── amplifier-dev/
    ├── dev-workflows.md
    ├── ecosystem-map.md
    └── testing-patterns.md
```

**Step 1: Copy all content files preserving subdirectory structure**

Run:
```bash
# Remove placeholder
rm -f services/svc-content-foundation/content/.gitkeep

# Copy preserving directory structure
cp -r related-projects/amplifier-foundation/context/* services/svc-content-foundation/content/
```

**Step 2: Verify all 20 files are present**

Run: `find services/svc-content-foundation/content/ -type f | sort | wc -l`

Expected: `20`

Run: `find services/svc-content-foundation/content/ -type f | sort`

Expected:
```
services/svc-content-foundation/content/CONTEXT_POISONING.md
services/svc-content-foundation/content/IMPLEMENTATION_PHILOSOPHY.md
services/svc-content-foundation/content/ISSUE_HANDLING.md
services/svc-content-foundation/content/KERNEL_PHILOSOPHY.md
services/svc-content-foundation/content/LANGUAGE_PHILOSOPHY.md
services/svc-content-foundation/content/MODULAR_DESIGN_PHILOSOPHY.md
services/svc-content-foundation/content/POLYGLOT_BUNDLES.md
services/svc-content-foundation/content/amplifier-dev/dev-workflows.md
services/svc-content-foundation/content/amplifier-dev/ecosystem-map.md
services/svc-content-foundation/content/amplifier-dev/testing-patterns.md
services/svc-content-foundation/content/amplifier-shadow-tests.md
services/svc-content-foundation/content/agents/delegation-instructions.md
services/svc-content-foundation/content/agents/multi-agent-patterns.md
services/svc-content-foundation/content/agents/session-repair-knowledge.md
services/svc-content-foundation/content/agents/session-storage-knowledge.md
services/svc-content-foundation/content/bundle-awareness.md
services/svc-content-foundation/content/shared/AWARENESS_INDEX.md
services/svc-content-foundation/content/shared/PROBLEM_SOLVING_PHILOSOPHY.md
services/svc-content-foundation/content/shared/common-agent-base.md
services/svc-content-foundation/content/shared/common-system-base.md
```

---

### Task 3: Create svc-content-foundation — describe.yaml with agents

**Files:**
- Create: `services/svc-content-foundation/describe.yaml`

The upstream repo at `related-projects/amplifier-foundation/agents/` contains 16 agent `.md` files. Each agent needs a short description in describe.yaml.

**Step 1: Create describe.yaml**

Create `services/svc-content-foundation/describe.yaml` with this exact content:

```yaml
name: svc-content-foundation
version: '0.1.0'
content_dir: content
agents:
  - name: amplifier-smoke-test
    description: Amplifier-specialized smoke test for shadow environments
  - name: bug-hunter
    description: Specialized debugging expert focused on finding and fixing bugs systematically
  - name: ecosystem-expert
    description: Amplifier ecosystem development specialist for cross-repository work
  - name: explorer
    description: Deep local-context reconnaissance agent for multi-file exploration
  - name: file-ops
    description: Focused file operations agent for reading, writing, editing, and searching files
  - name: foundation-expert
    description: Authoritative expert on Amplifier Foundation, bundle composition, and agent authoring
  - name: git-ops
    description: Git and GitHub operations agent with safety protocols and conventional commits
  - name: integration-specialist
    description: Expert at integrating with external services, APIs, and MCP servers
  - name: modular-builder
    description: Implementation-only agent that builds modules from complete specifications
  - name: post-task-cleanup
    description: Ensures codebase hygiene after task completion by reviewing and cleaning artifacts
  - name: security-guardian
    description: Security reviews, vulnerability assessments, and production deployment audits
  - name: session-analyst
    description: Analyzes, debugs, searches, and repairs Amplifier sessions and transcripts
  - name: shell-exec
    description: Shell command execution agent for running terminal commands safely
  - name: test-coverage
    description: Analyzes test coverage, identifies gaps, and suggests comprehensive test cases
  - name: web-research
    description: Web research agent for searching and fetching information from the internet
  - name: zen-architect
    description: Code planning, architecture design, and review with ruthless simplicity
```

**Step 2: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('services/svc-content-foundation/describe.yaml')); print('Valid YAML')"`

Expected: `Valid YAML`

**Step 3: Verify complete directory structure**

Run: `find services/svc-content-foundation/ -type f | head -5 && echo "..." && find services/svc-content-foundation/ -type f | wc -l`

Expected: 22 files total (1 Dockerfile + 1 describe.yaml + 20 content files)

**Step 4: Commit**

```bash
git add services/svc-content-foundation/
git commit -m "feat: create svc-content-foundation with 20 context files and 16 agents"
```

---

### Task 4: Port content to svc-content-browser-tester

**Files:**
- Create: `services/svc-content-browser-tester/content/browser-awareness.md`
- Create: `services/svc-content-browser-tester/content/browser-guide.md`
- Modify: `services/svc-content-browser-tester/describe.yaml` (no changes needed — agents already declared)

The upstream content is at `~/.amplifier/cache/amplifier-bundle-browser-tester-6b5f01b2acfa8ecc/context/`.

The describe.yaml already has the 3 agents declared (browser-operator, browser-researcher, visual-documenter) — no changes needed there.

**Step 1: Copy content files**

Run:
```bash
rm -f services/svc-content-browser-tester/content/.gitkeep
cp ~/.amplifier/cache/amplifier-bundle-browser-tester-*/context/*.md services/svc-content-browser-tester/content/
```

**Step 2: Verify files**

Run: `ls services/svc-content-browser-tester/content/`

Expected:
```
browser-awareness.md
browser-guide.md
```

**Step 3: Verify describe.yaml already has agents**

Run: `cat services/svc-content-browser-tester/describe.yaml`

Expected output should show `name: svc-content-browser-tester`, `content_dir: content`, and 3 agents (browser-operator, browser-researcher, visual-documenter). No modification needed.

**Step 4: Commit**

```bash
git add services/svc-content-browser-tester/
git commit -m "feat: port browser-tester content from upstream bundle (2 files)"
```

---

### Task 5: Port content to svc-content-design-intelligence

**Files:**
- Create: 15 files under `services/svc-content-design-intelligence/content/`
- Modify: `services/svc-content-design-intelligence/describe.yaml`

The upstream content is at `~/.amplifier/cache/amplifier-bundle-design-intelligence-5c95635236540259/context/` with this structure:

```
context/
├── design-instructions.md
├── knowledge-base/
│   ├── README.md
│   ├── accessibility.md
│   ├── animation-principles.md
│   ├── color-theory.md
│   └── typography.md
├── philosophy/
│   ├── DESIGN-FRAMEWORK.md
│   ├── DESIGN-PHILOSOPHY.md
│   ├── DESIGN-PRINCIPLES.md
│   └── DESIGN-VISION.md
└── protocols/
    ├── ANTI-PATTERNS.md
    ├── COMPONENT-CREATION-PROTOCOL.md
    ├── DESIGN-CHECKLIST.md
    ├── REQUIREMENTS-TEMPLATE.md
    └── WIREFRAME-STANDARDS.md
```

7 agents: animation-choreographer, art-director, component-designer, design-system-architect, layout-architect, responsive-strategist, voice-strategist.

**Step 1: Copy content files preserving subdirectory structure**

Run:
```bash
rm -f services/svc-content-design-intelligence/content/.gitkeep
cp -r ~/.amplifier/cache/amplifier-bundle-design-intelligence-*/context/* services/svc-content-design-intelligence/content/
```

**Step 2: Verify file count**

Run: `find services/svc-content-design-intelligence/content/ -type f | wc -l`

Expected: `15`

**Step 3: Update describe.yaml with agents**

Replace the contents of `services/svc-content-design-intelligence/describe.yaml` with:

```yaml
name: svc-content-design-intelligence
version: '0.1.0'
content_dir: content
agents:
  - name: animation-choreographer
    description: Designs motion, animations, and transitions for UI elements
  - name: art-director
    description: Aesthetic direction, visual strategy, and cohesive visual expression
  - name: component-designer
    description: Designs and implements individual UI components with quality baseline
  - name: design-system-architect
    description: Design system architecture, design tokens, and design foundations
  - name: layout-architect
    description: Page-level layout structure, information architecture, and spatial composition
  - name: responsive-strategist
    description: Responsive design strategy, breakpoint behavior, and device-specific adaptations
  - name: voice-strategist
    description: Voice and tone strategy, UX writing, and microcopy
```

**Step 4: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('services/svc-content-design-intelligence/describe.yaml')); print('Valid YAML')"`

Expected: `Valid YAML`

**Step 5: Commit**

```bash
git add services/svc-content-design-intelligence/
git commit -m "feat: port design-intelligence content from upstream bundle (15 files, 7 agents)"
```

---

### Task 6: Port content to svc-content-filesystem

**Files:**
- Create: `services/svc-content-filesystem/content/editing-guidance.md`
- No describe.yaml changes needed (no agents for this service)

The upstream content is at `~/.amplifier/cache/amplifier-bundle-filesystem-800514b6bec1fdef/context/`.

**Step 1: Copy content file**

Run:
```bash
rm -f services/svc-content-filesystem/content/.gitkeep
cp ~/.amplifier/cache/amplifier-bundle-filesystem-*/context/editing-guidance.md services/svc-content-filesystem/content/
```

**Step 2: Verify**

Run: `ls services/svc-content-filesystem/content/`

Expected: `editing-guidance.md`

**Step 3: Verify describe.yaml is correct as-is**

Run: `cat services/svc-content-filesystem/describe.yaml`

Expected:
```yaml
name: svc-content-filesystem
version: '0.1.0'
content_dir: content
```

No agents to declare — this is a content-only service. No modification needed.

**Step 4: Commit**

```bash
git add services/svc-content-filesystem/
git commit -m "feat: port filesystem content from upstream bundle (1 file)"
```

---

### Task 7: Port content to svc-content-recipes

**Files:**
- Create: `services/svc-content-recipes/content/recipe-awareness.md`
- Create: `services/svc-content-recipes/content/recipe-instructions.md`
- Modify: `services/svc-content-recipes/describe.yaml`

The upstream content is at `~/.amplifier/cache/amplifier-bundle-recipes-2b1e350432fea9ba/context/`.

2 agents: recipe-author, result-validator.

**Step 1: Copy content files**

Run:
```bash
rm -f services/svc-content-recipes/content/.gitkeep
cp ~/.amplifier/cache/amplifier-bundle-recipes-*/context/*.md services/svc-content-recipes/content/
```

**Step 2: Verify files**

Run: `ls services/svc-content-recipes/content/`

Expected:
```
recipe-awareness.md
recipe-instructions.md
```

**Step 3: Update describe.yaml with agents**

Replace the contents of `services/svc-content-recipes/describe.yaml` with:

```yaml
name: svc-content-recipes
version: '0.1.0'
content_dir: content
agents:
  - name: recipe-author
    description: Conversational recipe expert for creation, editing, validation, and debugging of Amplifier recipes
  - name: result-validator
    description: Objective pass/fail validation agent for recipes, workflows, and deployment outcomes
```

**Step 4: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('services/svc-content-recipes/describe.yaml')); print('Valid YAML')"`

Expected: `Valid YAML`

**Step 5: Commit**

```bash
git add services/svc-content-recipes/
git commit -m "feat: port recipes content from upstream bundle (2 files, 2 agents)"
```

---

### Task 8: Port content to svc-content-superpowers

**Files:**
- Create: 6 files under `services/svc-content-superpowers/content/`
- Modify: `services/svc-content-superpowers/describe.yaml`

The upstream content is at `~/.amplifier/cache/amplifier-bundle-superpowers-1e7a6ff3d51f6d25/context/`.

Content files: debugging-techniques.md, instructions.md, philosophy.md, shared-anti-rationalization.md, tdd-depth.md, using-superpowers-amplifier.md

5 agents: brainstormer, code-quality-reviewer, implementer, plan-writer, spec-reviewer.

**Step 1: Copy content files**

Run:
```bash
rm -f services/svc-content-superpowers/content/.gitkeep
cp ~/.amplifier/cache/amplifier-bundle-superpowers-*/context/*.md services/svc-content-superpowers/content/
```

**Step 2: Verify files**

Run: `ls services/svc-content-superpowers/content/ | sort`

Expected:
```
debugging-techniques.md
instructions.md
philosophy.md
shared-anti-rationalization.md
tdd-depth.md
using-superpowers-amplifier.md
```

**Step 3: Update describe.yaml with agents**

Replace the contents of `services/svc-content-superpowers/describe.yaml` with:

```yaml
name: svc-content-superpowers
version: '0.1.0'
content_dir: content
agents:
  - name: brainstormer
    description: Writes validated designs as formal documents after brainstorm-mode conversations
  - name: code-quality-reviewer
    description: Assesses code quality after spec compliance is confirmed
  - name: implementer
    description: Executes a single task from an implementation plan
  - name: plan-writer
    description: Formats validated plans as formal implementation documents
  - name: spec-reviewer
    description: Verifies spec compliance after an implementer completes a task
```

**Step 4: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('services/svc-content-superpowers/describe.yaml')); print('Valid YAML')"`

Expected: `Valid YAML`

**Step 5: Commit**

```bash
git add services/svc-content-superpowers/
git commit -m "feat: port superpowers content from upstream bundle (6 files, 5 agents)"
```

---

### Task 9: Remove svc-content-system-design-intelligence

**Files:**
- Delete: `services/svc-content-system-design-intelligence/` (entire directory)

This service was created speculatively — no upstream bundle exists for it. The design-intelligence bundle is already served by svc-content-design-intelligence (updated in Task 5).

**Step 1: Delete the service directory**

Run:
```bash
rm -rf services/svc-content-system-design-intelligence/
```

**Step 2: Verify removal**

Run: `ls services/svc-content-system-design-intelligence/ 2>&1`

Expected: `ls: cannot access 'services/svc-content-system-design-intelligence/': No such file or directory`

**Step 3: Commit**

```bash
git add -A services/svc-content-system-design-intelligence/
git commit -m "chore: remove speculative svc-content-system-design-intelligence (no upstream bundle)"
```

---

### Task 10: Update agents/foundation.yaml

**Files:**
- Modify: `agents/foundation.yaml`

Two changes:
1. Add `content-foundation` to the behaviors section
2. Remove `content-system-design-intelligence` from the behaviors section

**Step 1: Add content-foundation behavior**

In `agents/foundation.yaml`, after the `content-superpowers` block (line 100), add:

```yaml

    content-foundation:
      build: ./services/svc-content-foundation
```

**Step 2: Remove content-system-design-intelligence behavior**

In `agents/foundation.yaml`, remove these lines:

```yaml
    content-system-design-intelligence:
      build: ./services/svc-content-system-design-intelligence
```

**Step 3: Verify the result**

Run: `grep 'content-' agents/foundation.yaml`

Expected output should show these content services (and NOT show content-system-design-intelligence):
```
    content-core:
    content-amplifier:
    content-browser-tester:
    content-design-intelligence:
    content-filesystem:
    content-recipes:
    content-superpowers:
    content-foundation:
```

**Step 4: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('agents/foundation.yaml')); print('Valid YAML')"`

Expected: `Valid YAML`

---

### Task 11: Update agents/default.yaml

**Files:**
- Modify: `agents/default.yaml`

Same two changes as foundation.yaml:
1. Add `content-foundation` to the behaviors section
2. Remove `content-system-design-intelligence` from the behaviors section

**Step 1: Add content-foundation behavior**

In `agents/default.yaml`, after the `content-superpowers` block (line 91), add:

```yaml

    content-foundation:
      build: ./services/svc-content-foundation
```

**Step 2: Remove content-system-design-intelligence behavior**

In `agents/default.yaml`, remove these lines:

```yaml
    content-system-design-intelligence:
      build: ./services/svc-content-system-design-intelligence
```

**Step 3: Verify the result**

Run: `grep 'content-' agents/default.yaml`

Expected output should show these content services (and NOT show content-system-design-intelligence):
```
    content-core:
    content-amplifier:
    content-browser-tester:
    content-design-intelligence:
    content-filesystem:
    content-recipes:
    content-superpowers:
    content-foundation:
```

**Step 4: Verify YAML is valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('agents/default.yaml')); print('Valid YAML')"`

Expected: `Valid YAML`

**Step 5: Commit**

```bash
git add agents/foundation.yaml agents/default.yaml
git commit -m "feat: add content-foundation and remove content-system-design-intelligence from agent definitions"
```

---

### Task 12: Regenerate docker-compose.yaml

**Files:**
- Modify: `docker-compose.yaml` (auto-generated)

**Step 1: Run ampctl compose**

Run: `ampctl compose`

This reads all agent definitions in `agents/` and generates a merged `docker-compose.yaml`.

**Step 2: Verify the new content-foundation service appears**

Run: `grep 'content-foundation' docker-compose.yaml`

Expected: At least one line containing the svc-content-foundation service definition.

**Step 3: Verify the removed service is gone**

Run: `grep 'system-design-intelligence' docker-compose.yaml`

Expected: No output (empty — the service should not appear).

**Step 4: Verify all content services are present**

Run: `grep -c 'svc-content-' docker-compose.yaml`

Expected: Multiple matches — one for each of the 8 content services (amplifier, core, foundation, browser-tester, design-intelligence, filesystem, recipes, superpowers).

**Step 5: Commit**

```bash
git add docker-compose.yaml
git commit -m "chore: regenerate docker-compose.yaml with content-foundation and without system-design-intelligence"
```

---

### Task 13: Final verification

**Files:** None (verification only)

**Step 1: Verify all content services have content (no empty content/ dirs)**

Run:
```bash
for svc in services/svc-content-*/; do
  name=$(basename "$svc")
  count=$(find "$svc/content" -type f ! -name '.gitkeep' 2>/dev/null | wc -l)
  echo "$name: $count files"
done
```

Expected:
```
svc-content-amplifier: 3 files
svc-content-browser-tester: 2 files
svc-content-core: 2 files
svc-content-design-intelligence: 15 files
svc-content-filesystem: 1 files
svc-content-foundation: 20 files
svc-content-recipes: 2 files
svc-content-superpowers: 6 files
```

**Step 2: Verify all describe.yaml files have agents where expected**

Run:
```bash
for svc in services/svc-content-*/; do
  name=$(basename "$svc")
  agents=$(grep -c '  - name:' "$svc/describe.yaml" 2>/dev/null || echo 0)
  echo "$name: $agents agents"
done
```

Expected:
```
svc-content-amplifier: 4 agents
svc-content-browser-tester: 3 agents
svc-content-core: 4 agents
svc-content-design-intelligence: 7 agents
svc-content-filesystem: 0 agents
svc-content-foundation: 16 agents
svc-content-recipes: 2 agents
svc-content-superpowers: 5 agents
```

**Step 3: Verify svc-content-system-design-intelligence is completely gone**

Run: `test -d services/svc-content-system-design-intelligence && echo "STILL EXISTS" || echo "Removed OK"`

Expected: `Removed OK`

**Step 4: Verify agent definitions don't reference removed service**

Run: `grep -r 'system-design-intelligence' agents/`

Expected: No output (empty).

**Step 5: Spot-check one content service Docker build (optional, takes ~60s)**

Run: `docker build -f services/svc-content-foundation/Dockerfile -t test-content-foundation . 2>&1 | tail -5`

Expected: Build succeeds with `Successfully tagged test-content-foundation:latest` or similar success message.

If the Docker build succeeds, clean up:
```bash
docker rmi test-content-foundation 2>/dev/null
```

---

## Summary

| Task | Service | Action | Content Files | Agents |
|------|---------|--------|--------------|--------|
| 1-3 | svc-content-foundation | CREATE | 20 | 16 |
| 4 | svc-content-browser-tester | UPDATE | 2 | 3 (existing) |
| 5 | svc-content-design-intelligence | UPDATE | 15 | 7 |
| 6 | svc-content-filesystem | UPDATE | 1 | 0 |
| 7 | svc-content-recipes | UPDATE | 2 | 2 |
| 8 | svc-content-superpowers | UPDATE | 6 | 5 |
| 9 | svc-content-system-design-intelligence | DELETE | — | — |
| 10-11 | foundation.yaml + default.yaml | UPDATE | — | — |
| 12 | docker-compose.yaml | REGENERATE | — | — |
| 13 | — | VERIFY | — | — |

**Totals:** 46 content files ported, 33 agent declarations across 7 active content services, 1 speculative service removed, 2 agent definitions updated, compose regenerated.