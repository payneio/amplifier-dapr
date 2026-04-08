#!/usr/bin/env python3
"""Deterministic parser for Amplifier bundle composition.

Reads registry.json, walks the transitive dependency tree for a target bundle,
parses all component files (modes, agents, recipes, skills, behavior YAMLs,
context files), and outputs a JSON manifest to stdout.

Usage:
    python parse_bundle_composition.py <bundle_name> <registry_path>
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


# -- Inlined utilities (from amplifier_foundation.bundle_docs) -----------------
# These are small functions inlined to keep the script self-contained.
# Source: amplifier_foundation/bundle_docs/frontmatter.py + token_cost.py

_MENTION_RE = re.compile(r"@([a-zA-Z0-9_][a-zA-Z0-9_.-]*):([a-zA-Z0-9_./-]+)")


def _strip_code(text: str) -> str:
    """Remove fenced and inline code blocks from text."""
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = re.sub(r"`[^`]+`", "", cleaned)
    return cleaned


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a .md or .yaml file.

    For .yaml/.yml files the entire content is parsed as YAML and
    the body is an empty string.

    For .md files the --- delimited frontmatter is parsed and
    everything after the closing --- is returned as the body.

    Returns (frontmatter_dict, body_str).
    """
    content = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(content) or {}
        return data, ""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            data = yaml.safe_load(parts[1]) or {}
            return data, parts[2]
        if len(parts) == 2:
            data = yaml.safe_load(parts[1]) or {}
            return data, ""
    return {}, content


def extract_mentions(text: str) -> list[str]:
    """Extract @namespace:path mentions from text, skipping code blocks."""
    cleaned = _strip_code(text)
    seen: set[str] = set()
    mentions: list[str] = []
    for match in _MENTION_RE.finditer(cleaned):
        mention = f"@{match.group(1)}:{match.group(2)}"
        if mention not in seen:
            seen.add(mention)
            mentions.append(mention)
    return mentions


_DELEGATION_RE = re.compile(r"\b([a-z][a-z0-9-]*):([a-z][a-z0-9-]+)\b(?![/.])")


def extract_delegation_targets(text: str) -> list[str]:
    """Extract namespace:agent-name delegation patterns from text."""
    cleaned = _strip_code(text)
    seen: set[str] = set()
    targets: list[str] = []
    for match in _DELEGATION_RE.finditer(cleaned):
        namespace = match.group(1)
        if namespace in ("http", "https", "git"):
            continue
        full = match.group(0)
        if full not in seen:
            seen.add(full)
            targets.append(full)
    return targets


def estimate_tokens(content: str) -> int:
    """Estimate token count: len(content) // 4."""
    return len(content) // 4


# -- Data Structures -----------------------------------------------------------


@dataclass
class ToolModuleRef:
    module: str
    source: str
    config_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"module": self.module, "source": self.source}
        if self.config_summary is not None:
            d["config_summary"] = self.config_summary
        return d


@dataclass
class ModeFields:
    name: str
    shortcut: str | None
    tool_categories: dict[str, list[str]]
    default_action: str
    allowed_transitions: list[str]
    allow_clear: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentFields:
    name: str
    meta_description_raw: str | None
    model_role: list[str]
    tool_modules: list[ToolModuleRef]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "meta_description_raw": self.meta_description_raw,
            "model_role": self.model_role,
            "tool_modules": [t.to_dict() for t in self.tool_modules],
        }


@dataclass
class RecipeStepSummary:
    id: str
    type: str | None
    agent: str | None
    condition: str | None
    output: str | None
    foreach: str | None
    parallel: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataFlowEntry:
    produced_by: str
    consumed_by: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalGate:
    stage: str
    requires_approval: bool
    approval_context_template: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecipeFields:
    name: str
    version: str | None
    tags: list[str]
    execution_mode: str
    input_interface: dict[str, list[str]]
    steps: list[RecipeStepSummary]
    data_flow: dict[str, DataFlowEntry]
    approval_gates: list[ApprovalGate]
    sub_recipe_calls: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "tags": self.tags,
            "execution_mode": self.execution_mode,
            "input_interface": self.input_interface,
            "steps": [s.to_dict() for s in self.steps],
            "data_flow": {k: v.to_dict() for k, v in self.data_flow.items()},
            "approval_gates": [g.to_dict() for g in self.approval_gates],
            "sub_recipe_calls": self.sub_recipe_calls,
        }


@dataclass
class SkillFields:
    name: str
    context_mode: str | None
    disable_model_invocation: bool
    user_invocable: bool
    model_role: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BehaviorYamlFields:
    name: str
    tool_modules: list[ToolModuleRef]
    hook_modules: list[ToolModuleRef]
    context_includes: list[str]
    agent_includes: list[str]
    nested_behavior_includes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tool_modules": [t.to_dict() for t in self.tool_modules],
            "hook_modules": [t.to_dict() for t in self.hook_modules],
            "context_includes": self.context_includes,
            "agent_includes": self.agent_includes,
            "nested_behavior_includes": self.nested_behavior_includes,
        }


@dataclass
class ParsedManifest:
    file_path: str
    component_type: str  # mode|agent|recipe|skill|behavior_yaml|context_file
    bundle_origin: str
    description: str | None
    eager_mentions: list[str]
    needs_llm: bool = False
    mode: ModeFields | None = None
    agent: AgentFields | None = None
    recipe: RecipeFields | None = None
    skill: SkillFields | None = None
    behavior_yaml: BehaviorYamlFields | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "file_path": self.file_path,
            "component_type": self.component_type,
            "bundle_origin": self.bundle_origin,
            "description": self.description,
            "eager_mentions": self.eager_mentions,
            "needs_llm": self.needs_llm,
        }
        for field_name in ("mode", "agent", "recipe", "skill", "behavior_yaml"):
            val = getattr(self, field_name)
            if val is not None:
                d[field_name] = val.to_dict()
        return d


# -- Registry Walker -----------------------------------------------------------


def _resolve_null_path(bundle_name: str, bundles: dict) -> str | None:
    """Find a parent bundle's local_path for a bundle with null local_path.

    Searches all registry bundles for one whose 'includes' list contains
    bundle_name AND has a non-null local_path that is not a .yaml/.yml file
    (i.e., is a directory path).

    When multiple candidates exist, prefers the parent whose name is the
    longest prefix of bundle_name (most specific name match), falling back
    to the first valid candidate otherwise.  This handles cases where a
    meta-bundle (e.g. ``foundation``) and an owning bundle (e.g.
    ``superpowers``) both list a null-path bundle in their ``includes``.

    Args:
        bundle_name: The bundle name with a null local_path to resolve.
        bundles: The full bundles dict from the registry.

    Returns:
        The resolved local_path string from the parent bundle, or None if
        no suitable parent is found.
    """
    candidates: list[tuple[str, str]] = []
    for bname, entry in bundles.items():
        if bundle_name not in (entry.get("includes") or []):
            continue
        parent_path = entry.get("local_path")
        if parent_path is None:
            continue
        if parent_path.endswith(".yaml") or parent_path.endswith(".yml"):
            continue
        candidates.append((bname, parent_path))

    if not candidates:
        return None

    # Prefer the parent whose name is the longest prefix of bundle_name.
    # e.g. for 'superpowers-methodology-behavior', prefer 'superpowers' over
    # 'foundation' because 'superpowers-methodology-behavior'.startswith('superpowers').
    prefix_candidates = [
        (bname, path) for bname, path in candidates if bundle_name.startswith(bname)
    ]
    if prefix_candidates:
        # Pick the most specific (longest) matching prefix
        return max(prefix_candidates, key=lambda x: len(x[0]))[1]

    # Fall back to the first valid candidate
    return candidates[0][1]


def load_registry(registry_path: Path) -> dict[str, Any]:
    """Read registry.json and return the bundles dict.

    Args:
        registry_path: Path to the registry.json file.

    Returns:
        The 'bundles' dict from the registry, mapping bundle name to bundle entry.
    """
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    return data["bundles"]


def discover_component_files(local_path: Path) -> list[tuple[Path, str]]:
    """Discover all component files under a bundle's local_path.

    If local_path is a file (non-root behavior YAML), returns that file as
    [(local_path, 'behavior_yaml')].

    If local_path is a directory, scans known subdirectories:
        modes/*.md          -> 'mode'
        agents/*.md         -> 'agent'
        recipes/*.yaml|yml  -> 'recipe'
        skills/*/SKILL.md   -> 'skill'
        behaviors/*.yaml|yml -> 'behavior_yaml'
        context/**/*.md     -> 'context_file'

    Returns [] for empty directories or non-existent paths.
    Files are sorted within each directory.

    Args:
        local_path: Path to a bundle directory or a behavior YAML file.

    Returns:
        A list of (path, component_type) tuples.
    """
    if not local_path.exists():
        return []

    if local_path.is_file():
        return [(local_path, "behavior_yaml")]

    result: list[tuple[Path, str]] = []

    # modes/*.md -> 'mode'
    modes_dir = local_path / "modes"
    if modes_dir.is_dir():
        result.extend((p, "mode") for p in sorted(modes_dir.glob("*.md")))

    # agents/*.md -> 'agent'
    agents_dir = local_path / "agents"
    if agents_dir.is_dir():
        result.extend((p, "agent") for p in sorted(agents_dir.glob("*.md")))

    # recipes/*.yaml|*.yml -> 'recipe'
    recipes_dir = local_path / "recipes"
    if recipes_dir.is_dir():
        recipe_files = sorted(
            list(recipes_dir.glob("*.yaml")) + list(recipes_dir.glob("*.yml"))
        )
        result.extend((p, "recipe") for p in recipe_files)

    # skills/*/SKILL.md -> 'skill'
    skills_dir = local_path / "skills"
    if skills_dir.is_dir():
        result.extend((p, "skill") for p in sorted(skills_dir.glob("*/SKILL.md")))

    # behaviors/*.yaml|*.yml -> 'behavior_yaml'
    behaviors_dir = local_path / "behaviors"
    if behaviors_dir.is_dir():
        behavior_files = sorted(
            list(behaviors_dir.glob("*.yaml")) + list(behaviors_dir.glob("*.yml"))
        )
        result.extend((p, "behavior_yaml") for p in behavior_files)

    # context/**/*.md (recursive) -> 'context_file'
    context_dir = local_path / "context"
    if context_dir.is_dir():
        result.extend((p, "context_file") for p in sorted(context_dir.rglob("*.md")))

    return result


# -- Per-Type Parsers ----------------------------------------------------------

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def parse_mode(path: Path, bundle_origin: str) -> ParsedManifest:
    """Parse a mode .md file with YAML frontmatter.

    Expects frontmatter with a 'mode' key containing: name, description,
    shortcut, tools (safe/warn/confirm lists), default_action,
    allowed_transitions, allow_clear.  Extracts @mentions from the body.
    """
    fm, body = parse_frontmatter(path)
    mode_data = fm.get("mode") or {}
    tools_data = mode_data.get("tools") or {}
    tool_categories: dict[str, list[str]] = {
        "safe": list(tools_data.get("safe") or []),
        "warn": list(tools_data.get("warn") or []),
        "confirm": list(tools_data.get("confirm") or []),
    }
    return ParsedManifest(
        file_path=str(path),
        component_type="mode",
        bundle_origin=bundle_origin,
        description=mode_data.get("description"),
        eager_mentions=extract_mentions(body),
        mode=ModeFields(
            name=mode_data.get("name", path.stem),
            shortcut=mode_data.get("shortcut"),
            tool_categories=tool_categories,
            default_action=mode_data.get("default_action", "warn"),
            allowed_transitions=list(mode_data.get("allowed_transitions") or []),
            allow_clear=bool(mode_data.get("allow_clear", False)),
        ),
    )


def parse_agent(path: Path, bundle_origin: str) -> ParsedManifest:
    """Parse an agent .md file with YAML frontmatter.

    Expects frontmatter with meta.name, meta.description, model_role (string
    or list -> always stored as list), and tools list (each with module/source).
    Extracts @mentions from the body.
    """
    fm, body = parse_frontmatter(path)
    meta = fm.get("meta") or {}

    raw_role = fm.get("model_role", [])
    if isinstance(raw_role, str):
        model_role: list[str] = [raw_role]
    else:
        model_role = list(raw_role or [])

    tools_raw = fm.get("tools") or []
    tool_modules: list[ToolModuleRef] = []
    for t in tools_raw:
        if isinstance(t, dict):
            tool_modules.append(
                ToolModuleRef(
                    module=t.get("module", ""),
                    source=t.get("source", ""),
                )
            )

    return ParsedManifest(
        file_path=str(path),
        component_type="agent",
        bundle_origin=bundle_origin,
        description=meta.get("description"),
        eager_mentions=extract_mentions(body),
        agent=AgentFields(
            name=meta.get("name", path.stem),
            meta_description_raw=meta.get("description"),
            model_role=model_role,
            tool_modules=tool_modules,
        ),
    )


def parse_recipe(path: Path, bundle_origin: str) -> ParsedManifest:
    """Parse a recipe .yaml file.

    Detects execution_mode as 'staged' when a 'stages' key is present,
    otherwise 'flat'.  Builds data_flow by tracking step outputs and scanning
    step data for {{var}} references.  Extracts approval_gates from stages
    with requires_approval=true.  Tracks sub_recipe_calls for steps with
    type='recipe'.
    """
    fm, _ = parse_frontmatter(path)

    name: str = fm.get("name", path.stem)
    description: str | None = fm.get("description")
    version: str | None = fm.get("version")
    tags: list[str] = list(fm.get("tags") or [])

    # Execution mode: staged if 'stages' key present, flat otherwise
    execution_mode = "staged" if "stages" in fm else "flat"

    # Collect flat steps list
    steps_raw: list[Any] = list(fm.get("steps") or [])
    steps: list[RecipeStepSummary] = []
    for step in steps_raw:
        if not isinstance(step, dict):
            continue
        steps.append(
            RecipeStepSummary(
                id=step.get("id", ""),
                type=step.get("type"),
                agent=step.get("agent"),
                condition=step.get("condition"),
                output=step.get("output"),
                foreach=step.get("foreach"),
                parallel=step.get("parallel"),
            )
        )

    # Build data_flow: map output variable -> producing step id
    output_producers: dict[str, str] = {}
    for step in steps:
        if step.output:
            output_producers[step.output] = step.id

    # Find consumers by scanning all step fields for {{var}} references
    consumers: dict[str, list[str]] = {v: [] for v in output_producers}
    for step_raw in steps_raw:
        if not isinstance(step_raw, dict):
            continue
        step_id = step_raw.get("id", "")
        step_text = json.dumps(step_raw)
        for var_name in _VAR_RE.findall(step_text):
            if var_name in consumers and step_id not in consumers[var_name]:
                consumers[var_name].append(step_id)

    data_flow: dict[str, DataFlowEntry] = {
        var: DataFlowEntry(produced_by=producer, consumed_by=consumers.get(var, []))
        for var, producer in output_producers.items()
    }

    # Approval gates: from stages that have requires_approval=true
    approval_gates: list[ApprovalGate] = []
    stages_raw: list[Any] = list(fm.get("stages") or [])
    for stage in stages_raw:
        if not isinstance(stage, dict):
            continue
        if stage.get("requires_approval"):
            approval_gates.append(
                ApprovalGate(
                    stage=stage.get("name", ""),
                    requires_approval=True,
                    approval_context_template=stage.get("approval_context_template"),
                )
            )

    # Sub-recipe calls: steps with type='recipe'
    sub_recipe_calls: list[dict[str, str]] = []
    for step_raw in steps_raw:
        if not isinstance(step_raw, dict):
            continue
        if step_raw.get("type") == "recipe":
            sub_recipe_calls.append(
                {
                    "step_id": step_raw.get("id", ""),
                    "recipe": step_raw.get("recipe", ""),
                }
            )

    return ParsedManifest(
        file_path=str(path),
        component_type="recipe",
        bundle_origin=bundle_origin,
        description=description,
        eager_mentions=[],
        recipe=RecipeFields(
            name=name,
            version=version,
            tags=tags,
            execution_mode=execution_mode,
            input_interface={"required": [], "optional": []},
            steps=steps,
            data_flow=data_flow,
            approval_gates=approval_gates,
            sub_recipe_calls=sub_recipe_calls,
        ),
    )


def parse_skill(path: Path, bundle_origin: str) -> ParsedManifest:
    """Parse a SKILL.md file with YAML frontmatter.

    Expects frontmatter with: name, description, context_mode,
    disable_model_invocation, user_invocable, model_role.
    Extracts @mentions from the body.
    """
    fm, body = parse_frontmatter(path)
    return ParsedManifest(
        file_path=str(path),
        component_type="skill",
        bundle_origin=bundle_origin,
        description=fm.get("description"),
        eager_mentions=extract_mentions(body),
        skill=SkillFields(
            name=fm.get("name", path.parent.name),
            context_mode=fm.get("context_mode"),
            disable_model_invocation=bool(fm.get("disable_model_invocation", False)),
            user_invocable=bool(fm.get("user_invocable", False)),
            model_role=fm.get("model_role"),
        ),
    )


def parse_behavior_yaml(path: Path, bundle_origin: str) -> ParsedManifest:
    """Parse a behavior .yaml file.

    Expects top-level keys: bundle (with name/description), tools list,
    hooks list, context.include list, agents.include list, and includes list
    (each item may be a dict with a 'bundle' key, or a plain string).
    """
    fm, _ = parse_frontmatter(path)

    bundle_data = fm.get("bundle") or {}
    name: str = bundle_data.get("name", path.stem)
    description: str | None = bundle_data.get("description")

    def _to_tool_refs(raw: Any) -> list[ToolModuleRef]:
        refs: list[ToolModuleRef] = []
        for item in raw or []:
            if isinstance(item, dict):
                refs.append(
                    ToolModuleRef(
                        module=item.get("module", ""),
                        source=item.get("source", ""),
                    )
                )
            elif isinstance(item, str):
                refs.append(ToolModuleRef(module=item, source=""))
        return refs

    tool_modules = _to_tool_refs(fm.get("tools"))
    hook_modules = _to_tool_refs(fm.get("hooks"))

    context_data = fm.get("context") or {}
    context_includes: list[str] = list(context_data.get("include") or [])

    agents_data = fm.get("agents") or {}
    agent_includes: list[str] = list(agents_data.get("include") or [])

    # includes list: extract 'bundle' key from dicts, pass strings through
    nested_behavior_includes: list[str] = []
    for inc in fm.get("includes") or []:
        if isinstance(inc, dict):
            bundle_key = inc.get("bundle")
            if bundle_key:
                nested_behavior_includes.append(bundle_key)
        elif isinstance(inc, str):
            nested_behavior_includes.append(inc)

    return ParsedManifest(
        file_path=str(path),
        component_type="behavior_yaml",
        bundle_origin=bundle_origin,
        description=description,
        eager_mentions=[],
        behavior_yaml=BehaviorYamlFields(
            name=name,
            tool_modules=tool_modules,
            hook_modules=hook_modules,
            context_includes=context_includes,
            agent_includes=agent_includes,
            nested_behavior_includes=nested_behavior_includes,
        ),
    )


def parse_context_file(path: Path, bundle_origin: str) -> ParsedManifest:
    """Parse a context .md file.

    Reads the full file content and extracts @namespace:path mentions.
    Description is always None for context files.
    """
    content = path.read_text(encoding="utf-8")
    return ParsedManifest(
        file_path=str(path),
        component_type="context_file",
        bundle_origin=bundle_origin,
        description=None,
        eager_mentions=extract_mentions(content),
    )


def discover_cached_skills(registry_path: Path) -> list[tuple[Path, str]]:
    """Discover skills from the skills cache directory.

    Looks in ``registry_path.parent / "cache" / "skills"`` for files matching
    the pattern ``*/skills/*/SKILL.md``.  Each skill repo directory is a
    versioned checkout (e.g. ``superpowers-a6aca0133cf890bf``) that contains a
    ``skills/`` subdirectory with one directory per skill.

    Args:
        registry_path: Path to the registry.json file (e.g. ``~/.amplifier/registry.json``).
            The skills cache is resolved relative to its parent directory.

    Returns:
        A sorted list of ``(skill_md_path, "skill")`` tuples.  Returns ``[]``
        if the skills cache directory does not exist.
    """
    skills_cache = registry_path.parent / "cache" / "skills"
    if not skills_cache.exists():
        return []
    return [
        (skill_md, "skill")
        for skill_md in sorted(skills_cache.glob("*/skills/*/SKILL.md"))
    ]


def discover_skills_from_tool_configs(behavior_data: dict[str, Any]) -> list[str]:
    """Discover skill URIs from tool-skills entries in a behavior YAML dict.

    Scans the tools list for entries where module == 'tool-skills', then
    extracts all URIs from their config.skills arrays.

    Args:
        behavior_data: A parsed behavior YAML dict (top-level keys).

    Returns:
        A list of skill URI strings. Returns [] if:
        - 'tools' key is missing
        - no tool-skills entries found
        - config key missing on a tool-skills entry
        - config.skills entries that are not strings are skipped
    """
    skill_uris: list[str] = []
    tools = behavior_data.get("tools")
    if not tools:
        return []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("module") != "tool-skills":
            continue
        config = tool.get("config")
        if not isinstance(config, dict):
            continue
        skills = config.get("skills")
        if not skills:
            continue
        for skill in skills:
            if isinstance(skill, str):
                skill_uris.append(skill)
    return skill_uris


def classify_needs_llm(component_type: str, body: str) -> bool:
    """Determine if a file needs LLM extraction based on type and body content.

    Heuristic rules:
    - behavior_yaml: always False (pure config, no narrative content to extract)
    - recipe: True only if body contains 'prompt:' (indicates LLM-driven steps)
    - mode, agent, skill, context_file: True if body.strip() is non-empty
    - Empty/whitespace-only body: always False regardless of type

    Args:
        component_type: One of 'mode', 'agent', 'recipe', 'skill',
                        'behavior_yaml', 'context_file'.
        body: The body text of the file (after frontmatter, or full content).

    Returns:
        True if the file should be sent to an LLM for extraction, False otherwise.
    """
    if component_type == "behavior_yaml":
        return False
    if not body.strip():
        return False
    if component_type == "recipe":
        return "prompt:" in body
    # mode, agent, skill, context_file: non-empty body needs LLM
    return True


def resolve_dependency_tree(bundle_name: str, bundles: dict[str, Any]) -> list[str]:
    """Resolve the transitive dependency tree for a bundle via BFS.

    Traverses the 'includes' field of each bundle entry. Cycles are handled
    by a visited set. Bundle names not present in the registry are silently
    skipped.

    Args:
        bundle_name: The starting bundle to resolve from.
        bundles: The bundles dict (as returned by load_registry).

    Returns:
        A list of bundle names in BFS order, starting with bundle_name.
    """
    result: list[str] = []
    visited: set[str] = set()
    queue: deque[str] = deque([bundle_name])
    visited.add(bundle_name)

    while queue:
        current = queue.popleft()
        result.append(current)
        bundle_entry = bundles.get(current)
        if bundle_entry is None:
            continue
        for dep in bundle_entry.get("includes", []):
            if dep not in visited and dep in bundles:
                visited.add(dep)
                queue.append(dep)

    return result


# -- Parser Map ----------------------------------------------------------------

_PARSER_MAP: dict[str, Any] = {
    "mode": parse_mode,
    "agent": parse_agent,
    "recipe": parse_recipe,
    "skill": parse_skill,
    "behavior_yaml": parse_behavior_yaml,
    "context_file": parse_context_file,
}


# -- Main Script ---------------------------------------------------------------


def build_manifest(
    bundle_name: str,
    bundles: dict[str, Any],
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Build the full JSON manifest for a bundle and its transitive dependencies.

    Resolves the dependency tree, then for each bundle:
    - When local_path is None, attempts to resolve via _resolve_null_path (uses
      parent bundle's local_path).  Only adds to skipped_bundles if unresolvable.
    - Discovers component files
    - Parses each file using the appropriate parser
    - Sets needs_llm via classify_needs_llm
    - Collects skills_sources from behavior_yaml files

    After processing all registry bundles, also discovers skills from the skills
    cache (registry_path.parent/cache/skills/*/skills/*/SKILL.md) when
    registry_path is provided.  Deduplicates by skill name; registry-discovered
    skills take priority over cache-discovered ones.

    Args:
        bundle_name: The target bundle to build a manifest for.
        bundles: The bundles dict (as returned by load_registry).
        registry_path: Optional path to the registry.json file.  When provided,
            cached skills are also discovered and added to the manifest.

    Returns:
        A dict with keys:
        - bundle_name: The target bundle name
        - dependency_tree: List of bundle names in BFS order
        - manifests: List of all ParsedManifest dicts
        - llm_targets: Subset of manifests where needs_llm=True
        - skipped_bundles: List of bundle names with no resolvable local_path
        - skills_sources: List of skill URI strings from behavior_yaml tool-skills configs
    """
    dependency_tree = resolve_dependency_tree(bundle_name, bundles)

    manifests: list[dict[str, Any]] = []
    skipped_bundles: list[str] = []
    skills_sources: list[str] = []
    # Track skill names for deduplication (registry skills have priority)
    seen_skill_names: set[str] = set()

    for bname in dependency_tree:
        bundle_entry = bundles.get(bname, {})
        local_path_str = bundle_entry.get("local_path")

        if local_path_str is None:
            # Bug 1 fix: try to resolve via a parent bundle
            resolved = _resolve_null_path(bname, bundles)
            if resolved is None:
                skipped_bundles.append(bname)
                continue
            local_path_str = resolved

        local_path = Path(local_path_str)
        component_files = discover_component_files(local_path)

        for file_path, component_type in component_files:
            parser = _PARSER_MAP.get(component_type)
            if parser is None:
                continue

            try:
                manifest = parser(file_path, bname)

                # Get body for triage: parse_frontmatter returns (fm, body)
                # For YAML files: body="" ; For MD without frontmatter: body=full content
                fm, body = parse_frontmatter(file_path)
                manifest.needs_llm = classify_needs_llm(component_type, body)

                # Collect skill URIs from behavior_yaml tool-skills configs
                if component_type == "behavior_yaml":
                    skills_sources.extend(discover_skills_from_tool_configs(fm))

                # Track skill names to support deduplication with cached skills
                if component_type == "skill" and manifest.skill is not None:
                    seen_skill_names.add(manifest.skill.name)

                manifests.append(manifest.to_dict())
            except Exception as exc:
                logging.warning("Failed to parse %s: %s", file_path, exc)
                continue

    # Bug 2 fix: discover and parse skills from the skills cache, deduplicated
    # by skill name (registry-discovered skills above take priority).
    if registry_path is not None:
        for file_path, component_type in discover_cached_skills(registry_path):
            try:
                # Derive bundle_origin: strip trailing -<hexhash> from repo dir name
                # e.g. superpowers-a6aca0133cf890bf -> superpowers
                repo_dir_name = file_path.parent.parent.parent.name
                match = re.match(r"^(.+)-[0-9a-f]+$", repo_dir_name)
                cache_bundle_origin = match.group(1) if match else repo_dir_name

                manifest = parse_skill(file_path, cache_bundle_origin)

                # Deduplicate: skip if already discovered from the registry
                if manifest.skill is not None:
                    if manifest.skill.name in seen_skill_names:
                        continue
                    seen_skill_names.add(manifest.skill.name)

                fm, body = parse_frontmatter(file_path)
                manifest.needs_llm = classify_needs_llm(component_type, body)
                manifests.append(manifest.to_dict())
            except Exception as exc:
                logging.warning("Failed to parse cached skill %s: %s", file_path, exc)
                continue

    # Deduplicate by file_path (first occurrence wins)
    seen_paths: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for m in manifests:
        fp = m["file_path"] if isinstance(m, dict) else m.file_path
        path_key = str(fp)
        if path_key not in seen_paths:
            seen_paths.add(path_key)
            deduped.append(m)
    manifests = deduped

    llm_targets = [m for m in manifests if m.get("needs_llm") is True]

    return {
        "bundle_name": bundle_name,
        "dependency_tree": dependency_tree,
        "manifests": manifests,
        "llm_targets": llm_targets,
        "skipped_bundles": skipped_bundles,
        "skills_sources": skills_sources,
    }


def main() -> None:
    """CLI entrypoint: parse a bundle's composition and output JSON to stdout.

    Usage:
        python parse_bundle_composition.py <bundle_name> <registry_path>

    Exits with code 1 and prints an error JSON if the bundle is not found.
    """
    if len(sys.argv) != 3:
        error = {"error": f"Usage: {sys.argv[0]} <bundle_name> <registry_path>"}
        print(json.dumps(error))
        sys.exit(1)

    bundle_name = sys.argv[1]
    registry_path = Path(sys.argv[2]).expanduser()

    bundles = load_registry(registry_path)

    if bundle_name not in bundles:
        error = {"error": f"Bundle '{bundle_name}' not found in registry"}
        print(json.dumps(error))
        sys.exit(1)

    result = build_manifest(bundle_name, bundles, registry_path=registry_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
