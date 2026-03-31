# At-Mention Resolution Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Close 5 critical feature gaps in the IPC host's at-mention resolution pipeline to reach parity with the old Amplifier system.

**Architecture:** New `host/mentions.py` module with a composable resolver chain (`MentionResolverChain` with `NamespaceResolver` as default). The host owns the chain and pre-processes all `@mention` references. Recursive resolution uses SHA-256 dedup and a depth limit of 3. Four integration points: system prompt assembly, working directory content, agent spawn, and tool input pre-processing.

**Tech Stack:** Python 3.12+, pytest with `asyncio_mode = "auto"`, pydantic, uv

**Design Document:** `docs/plans/2026-03-25-at-mention-resolution-design.md`

**Scope:** Phases 1-2 only (core module + host wiring). Phase 3 (CLI integration) is a separate plan.

---

## Phase 1: Core `mentions.py` Module

All new code goes in `src/amplifier_ipc/host/mentions.py`. All tests go in `tests/host/test_mentions.py`.

---

### Task 1: `parse_mentions()` + `_remove_code_blocks()`

**Files:**
- Create: `src/amplifier_ipc/host/mentions.py`
- Create: `tests/host/test_mentions.py`

**Step 1: Write the failing tests**

Create `tests/host/test_mentions.py`:

```python
"""Tests for the mentions module — parsing, resolving, and loading @mentions."""

from __future__ import annotations

from amplifier_ipc.host.mentions import parse_mentions


# ---------------------------------------------------------------------------
# Tests: parse_mentions
# ---------------------------------------------------------------------------


def test_parse_mentions_extracts_namespace_path() -> None:
    """Extracts @namespace:path mentions from plain text."""
    result = parse_mentions("Load @foundation:context/common.md please")
    assert result == ["@foundation:context/common.md"]


def test_parse_mentions_multiple() -> None:
    """Extracts multiple distinct mentions preserving order."""
    text = "Use @foundation:context/a.md and @superpowers:context/b.md here"
    result = parse_mentions(text)
    assert result == ["@foundation:context/a.md", "@superpowers:context/b.md"]


def test_parse_mentions_excludes_fenced_code_blocks() -> None:
    """Mentions inside fenced code blocks are excluded."""
    text = "Before\n```\n@foundation:context/code.md\n```\nAfter @real:mention.md"
    result = parse_mentions(text)
    assert result == ["@real:mention.md"]


def test_parse_mentions_excludes_inline_code() -> None:
    """Mentions inside inline code are excluded."""
    text = "Use `@foundation:context/code.md` but also @real:mention.md"
    result = parse_mentions(text)
    assert result == ["@real:mention.md"]


def test_parse_mentions_deduplicates() -> None:
    """Duplicate mentions appear only once, preserving first occurrence order."""
    text = "@a:b.md and @a:b.md again"
    result = parse_mentions(text)
    assert result == ["@a:b.md"]


def test_parse_mentions_excludes_email_addresses() -> None:
    """Email-like patterns are not treated as mentions."""
    text = "Contact user@example.com and load @foundation:context/x.md"
    result = parse_mentions(text)
    assert result == ["@foundation:context/x.md"]


def test_parse_mentions_handles_tilde_path() -> None:
    """Tilde-prefixed paths like @~/path are extracted."""
    result = parse_mentions("Load @~/docs/AGENTS.md")
    assert result == ["@~/docs/AGENTS.md"]


def test_parse_mentions_handles_special_prefixes() -> None:
    """@user: and @project: prefixes are extracted."""
    text = "Load @user:skills/foo.md and @project:AGENTS.md"
    result = parse_mentions(text)
    assert result == ["@user:skills/foo.md", "@project:AGENTS.md"]


def test_parse_mentions_empty_text() -> None:
    """Empty text returns empty list."""
    assert parse_mentions("") == []


def test_parse_mentions_no_mentions() -> None:
    """Text with no mentions returns empty list."""
    assert parse_mentions("Just plain text with no at-signs of interest.") == []
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'amplifier_ipc.host.mentions'`

**Step 3: Write minimal implementation**

Create `src/amplifier_ipc/host/mentions.py`:

```python
"""Mention resolution — parse, resolve, and load @namespace:path references.

Provides:

* :func:`parse_mentions` — regex extraction of ``@namespace:path`` tokens from
  text, excluding code blocks, fenced blocks, and inline code.
* :class:`MentionResolver` — async callable protocol for mention resolution.
* :class:`NamespaceResolver` — resolves ``@namespace:path`` via ``content.read`` RPC.
* :class:`WorkingDirResolver` — resolves ``@~/``, ``@user:``, ``@project:``
  via local filesystem.
* :class:`MentionResolverChain` — ordered list of resolvers, first non-None wins.
* :func:`resolve_and_load` — recursive loader with SHA-256 dedup and depth limit.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from amplifier_ipc.host.service_index import ServiceIndex

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mention parsing
# ---------------------------------------------------------------------------

# Pattern: @ followed by word chars, colons, slashes, dots, hyphens, tildes.
# Negative lookahead excludes email addresses.
_MENTION_RE = re.compile(
    r"@(?![a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
    r"([a-zA-Z0-9_:./\~-]+)"
)


def _remove_code_blocks(text: str) -> str:
    """Remove fenced and inline code blocks from *text*.

    Fenced code blocks (````...````) must start at the beginning of a line
    per CommonMark spec.  Inline code (single backticks) is also removed,
    but adjacent triple-backtick sequences (like ``(```)``) are preserved.
    """
    # Remove fenced code blocks — ``` must be at start of line (or start of text)
    text = re.sub(
        r"(?:^|\n)```[^\n]*\n.*?(?:^|\n)```",
        "\n",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    # Remove inline code — single backticks, avoiding triple-backtick sequences
    text = re.sub(r"(?<!`)`(?!`)[^`]+(?<!`)`(?!`)", "", text)
    return text


def parse_mentions(text: str) -> list[str]:
    """Extract ``@namespace:path`` mentions from *text*, excluding code blocks.

    Returns unique mentions (including ``@`` prefix) in order of first
    appearance.  Mentions inside fenced code blocks, inline code, and
    email addresses are excluded.
    """
    text_clean = _remove_code_blocks(text)
    matches = _MENTION_RE.findall(text_clean)

    seen: set[str] = set()
    result: list[str] = []
    for match in matches:
        mention = f"@{match}"
        if mention not in seen:
            seen.add(mention)
            result.append(mention)
    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 10 tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py tests/host/test_mentions.py && git commit -m "feat(mentions): add parse_mentions with code block exclusion"
```

---

### Task 2: `MentionResolver` Protocol + `NamespaceResolver`

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py`
- Modify: `tests/host/test_mentions.py`

**Step 1: Write the failing tests**

Append to `tests/host/test_mentions.py`:

```python
from typing import Any

from amplifier_ipc.host.mentions import NamespaceResolver
from amplifier_ipc.host.service_index import ServiceIndex


# ---------------------------------------------------------------------------
# Fakes (shared across resolver tests)
# ---------------------------------------------------------------------------


class FakeClient:
    """Fake JSON-RPC client that serves content from an in-memory dict."""

    def __init__(self, content_map: dict[str, str]) -> None:
        self.content_map = content_map

    async def request(self, method: str, params: dict[str, str]) -> dict[str, str]:
        if method == "content.read":
            path = params["path"]
            if path not in self.content_map:
                raise KeyError(f"Unknown path: {path!r}")
            return {"content": self.content_map[path]}
        raise ValueError(f"Unsupported method: {method!r}")


class FakeService:
    """Minimal service stub with a fake client."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client


def _build_registry_and_services() -> tuple[ServiceIndex, dict[str, Any]]:
    """Create a registry and services dict with foundation and superpowers."""
    foundation_content: dict[str, str] = {
        "agents/explorer.md": "explorer agent content",
        "context/shared/common.md": "common shared content",
    }
    superpowers_content: dict[str, str] = {
        "context/philosophy.md": "philosophy content",
    }

    registry = ServiceIndex()
    registry.register(
        "foundation",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["agents/explorer.md", "context/shared/common.md"],
        },
    )
    registry.register(
        "superpowers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["context/philosophy.md"],
        },
    )

    services: dict[str, Any] = {
        "foundation": FakeService(FakeClient(foundation_content)),
        "superpowers": FakeService(FakeClient(superpowers_content)),
    }
    return registry, services


# ---------------------------------------------------------------------------
# Tests: NamespaceResolver
# ---------------------------------------------------------------------------


async def test_namespace_resolver_resolves_known_namespace() -> None:
    """Resolves @namespace:path to content via content.read RPC."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry, services)

    result = await resolver("@foundation:agents/explorer.md")

    assert result == "explorer agent content"


async def test_namespace_resolver_returns_none_for_unknown_namespace() -> None:
    """Returns None when the namespace is not in the content services."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry, services)

    result = await resolver("@unknown:some/path.md")

    assert result is None


async def test_namespace_resolver_returns_none_for_invalid_format() -> None:
    """Returns None when the mention has no colon separator."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry, services)

    result = await resolver("@invalidformat")

    assert result is None


async def test_namespace_resolver_returns_none_on_rpc_error() -> None:
    """Returns None (graceful degradation) when content.read RPC fails."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry, services)

    # Request a path that doesn't exist in FakeClient's content_map
    result = await resolver("@foundation:nonexistent/file.md")

    assert result is None


async def test_namespace_resolver_strips_at_prefix() -> None:
    """Works with or without the leading @ on the mention string."""
    registry, services = _build_registry_and_services()
    resolver = NamespaceResolver(registry, services)

    result = await resolver("foundation:agents/explorer.md")

    assert result == "explorer agent content"
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py::test_namespace_resolver_resolves_known_namespace -v`

Expected: FAIL — `ImportError: cannot import name 'NamespaceResolver'`

**Step 3: Write minimal implementation**

Add to `src/amplifier_ipc/host/mentions.py` (after `parse_mentions`):

```python
# ---------------------------------------------------------------------------
# Resolver protocol
# ---------------------------------------------------------------------------


class MentionResolver(Protocol):
    """Async callable that resolves a single mention to content.

    Returns the resolved content string, or ``None`` to pass resolution
    to the next resolver in the chain.
    """

    async def __call__(self, mention: str) -> str | None: ...


# ---------------------------------------------------------------------------
# NamespaceResolver
# ---------------------------------------------------------------------------


class NamespaceResolver:
    """Resolve ``@namespace:path`` mentions via ``content.read`` RPC.

    Looks up the *namespace* in :meth:`ServiceIndex.get_content_services` and
    forwards a ``content.read`` request to the owning service.  Holds
    **references** to the mutable *registry* and *services* objects so that
    resolution works even when the resolver is created before services are
    discovered.

    Args:
        registry: A :class:`~amplifier_ipc.host.service_index.ServiceIndex`.
        services: Mapping of service key → service object (must expose
            ``.client.request(method, params)``).
    """

    def __init__(
        self, registry: ServiceIndex, services: dict[str, Any]
    ) -> None:
        self._registry = registry
        self._services = services

    async def __call__(self, mention: str) -> str | None:
        raw = mention.lstrip("@")
        if ":" not in raw:
            return None

        namespace, path = raw.split(":", 1)

        content_services = self._registry.get_content_services()
        if namespace not in content_services:
            return None

        service = self._services.get(namespace)
        if service is None:
            return None

        try:
            result = await service.client.request("content.read", {"path": path})
            return result["content"]
        except Exception:
            logger.warning("Failed to resolve mention %r via content.read", mention)
            return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 15 tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py tests/host/test_mentions.py && git commit -m "feat(mentions): add MentionResolver protocol and NamespaceResolver"
```

---

### Task 3: `WorkingDirResolver`

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py`
- Modify: `tests/host/test_mentions.py`

**Step 1: Write the failing tests**

Append to `tests/host/test_mentions.py`:

```python
from pathlib import Path

from amplifier_ipc.host.mentions import WorkingDirResolver


# ---------------------------------------------------------------------------
# Tests: WorkingDirResolver
# ---------------------------------------------------------------------------


async def test_working_dir_resolver_resolves_tilde_path(tmp_path: Path) -> None:
    """Resolves @~/path relative to the user's home directory."""
    # Create a file under a fake home directory
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    target = fake_home / "docs" / "AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text("tilde content")

    resolver = WorkingDirResolver(working_dir=tmp_path, home_dir=fake_home)

    result = await resolver("@~/docs/AGENTS.md")

    assert result == "tilde content"


async def test_working_dir_resolver_resolves_user_path(tmp_path: Path) -> None:
    """Resolves @user:path relative to ~/.amplifier/."""
    fake_home = tmp_path / "home"
    target = fake_home / ".amplifier" / "skills" / "foo.md"
    target.parent.mkdir(parents=True)
    target.write_text("user content")

    resolver = WorkingDirResolver(working_dir=tmp_path, home_dir=fake_home)

    result = await resolver("@user:skills/foo.md")

    assert result == "user content"


async def test_working_dir_resolver_resolves_project_path(tmp_path: Path) -> None:
    """Resolves @project:path relative to working_dir/.amplifier/."""
    target = tmp_path / ".amplifier" / "AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text("project content")

    resolver = WorkingDirResolver(working_dir=tmp_path)

    result = await resolver("@project:AGENTS.md")

    assert result == "project content"


async def test_working_dir_resolver_returns_none_for_unhandled() -> None:
    """Returns None for mentions that don't match any prefix."""
    resolver = WorkingDirResolver(working_dir=Path("/tmp"))

    result = await resolver("@foundation:context/common.md")

    assert result is None


async def test_working_dir_resolver_returns_none_for_missing_file(
    tmp_path: Path,
) -> None:
    """Returns None when the target file doesn't exist."""
    resolver = WorkingDirResolver(working_dir=tmp_path)

    result = await resolver("@project:nonexistent.md")

    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py::test_working_dir_resolver_resolves_tilde_path -v`

Expected: FAIL — `ImportError: cannot import name 'WorkingDirResolver'`

**Step 3: Write minimal implementation**

Add to `src/amplifier_ipc/host/mentions.py` (after `NamespaceResolver`):

```python
# ---------------------------------------------------------------------------
# WorkingDirResolver
# ---------------------------------------------------------------------------


class WorkingDirResolver:
    """Resolve local-path mentions via the filesystem.

    Handles three prefixes:

    * ``@~/path`` — relative to the user's home directory.
    * ``@user:path`` — relative to ``~/.amplifier/``.
    * ``@project:path`` — relative to ``<working_dir>/.amplifier/``.

    Args:
        working_dir: The project working directory (usually ``cwd``).
        home_dir: Override for the home directory (defaults to
            :func:`Path.home`; pass explicitly in tests).
    """

    def __init__(
        self, working_dir: Path, home_dir: Path | None = None
    ) -> None:
        self._working_dir = working_dir
        self._home_dir = home_dir or Path.home()

    async def __call__(self, mention: str) -> str | None:
        raw = mention.lstrip("@")

        if raw.startswith("~/"):
            file_path = self._home_dir / raw[2:]
        elif raw.startswith("user:"):
            file_path = self._home_dir / ".amplifier" / raw[5:]
        elif raw.startswith("project:"):
            file_path = self._working_dir / ".amplifier" / raw[8:]
        else:
            return None

        try:
            return file_path.read_text()
        except (FileNotFoundError, OSError):
            logger.warning(
                "Failed to read %s for mention %r", file_path, mention
            )
            return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 20 tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py tests/host/test_mentions.py && git commit -m "feat(mentions): add WorkingDirResolver for local-path mentions"
```

---

### Task 4: `MentionResolverChain`

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py`
- Modify: `tests/host/test_mentions.py`

**Step 1: Write the failing tests**

Append to `tests/host/test_mentions.py`:

```python
from amplifier_ipc.host.mentions import MentionResolverChain


# ---------------------------------------------------------------------------
# Tests: MentionResolverChain
# ---------------------------------------------------------------------------


async def test_chain_resolve_first_wins() -> None:
    """First resolver that returns non-None wins."""

    async def resolver_a(mention: str) -> str | None:
        return "from A"

    async def resolver_b(mention: str) -> str | None:
        return "from B"

    chain = MentionResolverChain([resolver_a, resolver_b])
    result = await chain.resolve("@anything")

    assert result == "from A"


async def test_chain_resolve_skips_none() -> None:
    """Resolvers returning None are skipped; next resolver is tried."""

    async def resolver_skip(mention: str) -> str | None:
        return None

    async def resolver_hit(mention: str) -> str | None:
        return "found it"

    chain = MentionResolverChain([resolver_skip, resolver_hit])
    result = await chain.resolve("@anything")

    assert result == "found it"


async def test_chain_resolve_all_none() -> None:
    """Returns None when all resolvers return None."""

    async def resolver_skip(mention: str) -> str | None:
        return None

    chain = MentionResolverChain([resolver_skip])
    result = await chain.resolve("@anything")

    assert result is None


async def test_chain_prepend() -> None:
    """Prepended resolver is tried before existing resolvers."""

    async def original(mention: str) -> str | None:
        return "original"

    async def prepended(mention: str) -> str | None:
        return "prepended"

    chain = MentionResolverChain([original])
    chain.prepend(prepended)
    result = await chain.resolve("@anything")

    assert result == "prepended"


async def test_chain_append() -> None:
    """Appended resolver is tried after existing resolvers."""

    async def original(mention: str) -> str | None:
        return None

    async def appended(mention: str) -> str | None:
        return "appended"

    chain = MentionResolverChain([original])
    chain.append(appended)
    result = await chain.resolve("@anything")

    assert result == "appended"


async def test_chain_empty() -> None:
    """Empty chain returns None for any mention."""
    chain = MentionResolverChain()
    result = await chain.resolve("@anything")

    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py::test_chain_resolve_first_wins -v`

Expected: FAIL — `ImportError: cannot import name 'MentionResolverChain'`

**Step 3: Write minimal implementation**

Add to `src/amplifier_ipc/host/mentions.py` (after `WorkingDirResolver`):

```python
# ---------------------------------------------------------------------------
# MentionResolverChain
# ---------------------------------------------------------------------------


class MentionResolverChain:
    """Ordered chain of :class:`MentionResolver` instances.

    Tries each resolver in order; the first non-``None`` result wins.
    Use :meth:`prepend` and :meth:`append` to customise the chain at
    runtime (e.g. the CLI prepends a :class:`WorkingDirResolver` before
    calling ``host.run()``).

    Args:
        resolvers: Initial ordered list of resolvers.  Defaults to empty.
    """

    def __init__(
        self, resolvers: list[MentionResolver] | None = None
    ) -> None:
        self._resolvers: list[MentionResolver] = (
            list(resolvers) if resolvers else []
        )

    def prepend(self, resolver: MentionResolver) -> None:
        """Insert *resolver* at the front of the chain (highest priority)."""
        self._resolvers.insert(0, resolver)

    def append(self, resolver: MentionResolver) -> None:
        """Add *resolver* to the end of the chain (lowest priority)."""
        self._resolvers.append(resolver)

    async def resolve(self, mention: str) -> str | None:
        """Try each resolver in order; return the first non-None result."""
        for resolver in self._resolvers:
            result = await resolver(mention)
            if result is not None:
                return result
        return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 26 tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py tests/host/test_mentions.py && git commit -m "feat(mentions): add MentionResolverChain with prepend/append API"
```

---

### Task 5: `ResolvedContent` + `resolve_and_load()`

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py`
- Modify: `tests/host/test_mentions.py`

**Step 1: Write the failing tests**

Append to `tests/host/test_mentions.py`:

```python
from amplifier_ipc.host.mentions import ResolvedContent, resolve_and_load


# ---------------------------------------------------------------------------
# Tests: resolve_and_load
# ---------------------------------------------------------------------------


async def test_resolve_and_load_resolves_mentions() -> None:
    """Finds and resolves @mentions in the given text."""
    content_map = {
        "@svc:path/a.md": "content of A",
        "@svc:path/b.md": "content of B",
    }

    async def fake_resolver(mention: str) -> str | None:
        return content_map.get(mention)

    chain = MentionResolverChain([fake_resolver])
    text = "Load @svc:path/a.md and @svc:path/b.md"

    results = await resolve_and_load(text, chain)

    assert len(results) == 2
    assert results[0] == ResolvedContent(key="svc:path/a.md", content="content of A")
    assert results[1] == ResolvedContent(key="svc:path/b.md", content="content of B")


async def test_resolve_and_load_recursive() -> None:
    """Recursively resolves @mentions found in resolved content."""
    content_map = {
        "@svc:top.md": "Top references @svc:nested.md here",
        "@svc:nested.md": "nested content",
    }

    async def fake_resolver(mention: str) -> str | None:
        return content_map.get(mention)

    chain = MentionResolverChain([fake_resolver])
    text = "Load @svc:top.md"

    results = await resolve_and_load(text, chain)

    assert len(results) == 2
    assert results[0].key == "svc:top.md"
    assert results[1].key == "svc:nested.md"
    assert results[1].content == "nested content"


async def test_resolve_and_load_deduplicates_by_hash() -> None:
    """Same content (by SHA-256) is only returned once."""
    async def fake_resolver(mention: str) -> str | None:
        # Both mentions resolve to identical content
        if mention in ("@svc:a.md", "@svc:b.md"):
            return "same content"
        return None

    chain = MentionResolverChain([fake_resolver])
    text = "Load @svc:a.md and @svc:b.md"

    results = await resolve_and_load(text, chain)

    assert len(results) == 1
    assert results[0].content == "same content"


async def test_resolve_and_load_depth_limit() -> None:
    """Stops recursing at max_depth."""
    call_count = 0

    async def fake_resolver(mention: str) -> str | None:
        nonlocal call_count
        call_count += 1
        # Every resolved content references another mention — infinite chain
        return f"depth {call_count} references @svc:next{call_count}.md"

    chain = MentionResolverChain([fake_resolver])
    text = "Start @svc:start.md"

    results = await resolve_and_load(text, chain, max_depth=2)

    # depth=2: resolves start.md (depth 2→1), then next inside it (depth 1→0), stops
    assert len(results) == 2


async def test_resolve_and_load_shared_seen_hashes() -> None:
    """Content already in seen_hashes is skipped."""
    import hashlib

    async def fake_resolver(mention: str) -> str | None:
        return "already seen content"

    chain = MentionResolverChain([fake_resolver])
    already_seen = {hashlib.sha256(b"already seen content").hexdigest()}

    results = await resolve_and_load(
        "@svc:a.md", chain, seen_hashes=already_seen
    )

    assert results == []


async def test_resolve_and_load_skips_unresolved() -> None:
    """Mentions that resolve to None are silently skipped."""
    async def fake_resolver(mention: str) -> str | None:
        if mention == "@svc:exists.md":
            return "found"
        return None

    chain = MentionResolverChain([fake_resolver])
    text = "Load @svc:exists.md and @svc:missing.md"

    results = await resolve_and_load(text, chain)

    assert len(results) == 1
    assert results[0].key == "svc:exists.md"


async def test_resolve_and_load_handles_resolver_exception() -> None:
    """Resolver exceptions are caught and the mention is skipped."""
    async def flaky_resolver(mention: str) -> str | None:
        if mention == "@svc:ok.md":
            return "ok content"
        raise RuntimeError("RPC timeout")

    chain = MentionResolverChain([flaky_resolver])
    text = "Load @svc:bad.md and @svc:ok.md"

    results = await resolve_and_load(text, chain)

    assert len(results) == 1
    assert results[0].key == "svc:ok.md"
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py::test_resolve_and_load_resolves_mentions -v`

Expected: FAIL — `ImportError: cannot import name 'ResolvedContent'`

**Step 3: Write minimal implementation**

Add to `src/amplifier_ipc/host/mentions.py` (after `MentionResolverChain`):

```python
# ---------------------------------------------------------------------------
# Resolved content model
# ---------------------------------------------------------------------------


@dataclass
class ResolvedContent:
    """A single piece of resolved mention content.

    Attributes:
        key: The mention string without ``@`` prefix
             (e.g. ``"foundation:context/common.md"``).
        content: The resolved content text.
    """

    key: str
    content: str


# ---------------------------------------------------------------------------
# Recursive loader
# ---------------------------------------------------------------------------


async def resolve_and_load(
    text: str,
    chain: MentionResolverChain,
    *,
    seen_hashes: set[str] | None = None,
    max_depth: int = 3,
) -> list[ResolvedContent]:
    """Recursively resolve ``@mentions`` found in *text*.

    1. Parse mentions via :func:`parse_mentions`.
    2. Resolve each through *chain*.
    3. Deduplicate by SHA-256 hash (using shared *seen_hashes* set).
    4. Recurse into resolved content up to *max_depth*.

    Args:
        text: Text to scan for ``@mentions``.
        chain: Resolver chain to use.
        seen_hashes: Shared mutable set of SHA-256 hex digests for
            cross-call deduplication.  Created internally when ``None``.
        max_depth: Maximum recursion depth (default 3).

    Returns:
        List of :class:`ResolvedContent` items in resolution order.
        Only includes content not already in *seen_hashes*.
    """
    if max_depth <= 0:
        return []
    if seen_hashes is None:
        seen_hashes = set()

    mentions = parse_mentions(text)
    results: list[ResolvedContent] = []

    for mention in mentions:
        try:
            content = await chain.resolve(mention)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to resolve mention %r", mention)
            continue

        if content is None:
            continue

        h = hashlib.sha256(content.encode()).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        key = mention.lstrip("@")
        results.append(ResolvedContent(key=key, content=content))

        # Recurse into resolved content
        nested = await resolve_and_load(
            content, chain, seen_hashes=seen_hashes, max_depth=max_depth - 1
        )
        results.extend(nested)

    return results
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 33 tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py tests/host/test_mentions.py && git commit -m "feat(mentions): add resolve_and_load with recursive SHA-256 dedup"
```

---

## Phase 2: Wire Into Host

---

### Task 6: Update `content.py` — New Signature + Recursive Resolution

**Files:**
- Modify: `src/amplifier_ipc/host/content.py`
- Modify: `tests/host/test_content.py`

**Context:** The existing `resolve_mention()` function in `content.py` is now superseded by `NamespaceResolver` in `mentions.py`. The `assemble_system_prompt()` function needs a new `resolver_chain` parameter and should recursively resolve `@mentions` in gathered content. The old `mentions: list[str] | None` parameter is removed.

**Step 1: Update the tests**

In `tests/host/test_content.py`, make these changes:

1. Remove the import of `resolve_mention`:

Change line 12:
```python
from amplifier_ipc.host.content import assemble_system_prompt, resolve_mention
```
to:
```python
from amplifier_ipc.host.content import assemble_system_prompt
```

2. Remove the three `test_resolve_mention_*` tests (lines 105-127) entirely — they tested the old `resolve_mention()` function which is now `NamespaceResolver` (tested in `test_mentions.py`).

3. Update `test_assemble_system_prompt_with_mentions` (starting at line 149) to use `resolver_chain` instead of `mentions=`:

Replace the entire test function with:

```python
async def test_assemble_system_prompt_with_resolver_chain() -> None:
    """Recursively resolves @mentions in gathered content via resolver_chain."""
    # Set up a service whose context file contains an @mention
    content_with_mention: dict[str, str] = {
        "context/main.md": "Main doc references @superpowers:context/philosophy.md",
        "context/philosophy.md": "philosophy content",
    }

    registry = ServiceIndex()
    registry.register(
        "superpowers",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["context/main.md", "context/philosophy.md"],
        },
    )
    services = {"superpowers": FakeService(FakeClient(content_with_mention))}

    from amplifier_ipc.host.mentions import MentionResolverChain, NamespaceResolver

    chain = MentionResolverChain([NamespaceResolver(registry, services)])

    result = await assemble_system_prompt(
        registry, services, resolver_chain=chain
    )

    # Both files gathered as context, @mention in main.md resolved recursively
    # (but philosophy.md is already gathered, so dedup means no duplicate)
    assert "Main doc references" in result
    assert "philosophy content" in result
    assert result.count("philosophy content") == 1  # deduplicated
```

4. Update `test_assemble_system_prompt_deduplicates` (starting at line 164) — remove the `mentions=` parameter since we no longer have it:

Replace the entire test function with:

```python
async def test_assemble_system_prompt_deduplicates() -> None:
    """Same content appearing from multiple services is included only once."""
    registry, services = _build_registry_and_services()

    result = await assemble_system_prompt(registry, services)

    # The regular context/ files should each appear once
    assert result.count("common shared content") == 1
    assert result.count("philosophy content") == 1
```

5. Update the integration test `test_mention_resolution_end_to_end` (starting at line 326) to use `NamespaceResolver` instead of `resolve_mention`:

Replace the function with:

```python
async def test_mention_resolution_end_to_end(tmp_path: Path) -> None:
    """Integration: NamespaceResolver routes @namespace:path to the correct service.

    Verifies that after ``_build_registry()`` populates the content registry,
    ``NamespaceResolver`` can:

    * Fetch a non-context/ file (agents/explorer.md) that is excluded from
      auto-assembly but accessible via explicit @mention.
    * Fetch a context/ file by explicit @mention too.

    This exercises the @namespace routing logic with a real subprocess.
    """
    from amplifier_ipc.host.mentions import NamespaceResolver

    pkg_parent = _create_content_service_package(tmp_path)
    service = await _spawn_content_service(pkg_parent)

    config = SessionConfig(
        services=["content_svc"],
        orchestrator="",
        context_manager="",
        provider="",
    )
    host = Host(config=config, settings=HostSettings())
    host._services = {"content_svc": service}

    try:
        await host._build_registry()

        resolver = NamespaceResolver(host._registry, host._services)

        # agents/ file: excluded from auto-assembly but reachable via resolver
        agent_content = await resolver("@content_svc:agents/explorer.md")
        assert agent_content == "# Explorer Agent\nExplore things."

        # context/ file: also reachable via resolver
        ctx_content = await resolver("@content_svc:context/philosophy.md")
        assert ctx_content == "# Philosophy\nBe excellent."
    finally:
        await shutdown_service(service, timeout=5.0)
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_content.py -v`

Expected: FAIL — tests import `resolve_mention` which we haven't removed yet, and `test_assemble_system_prompt_with_resolver_chain` uses the new parameter

**Step 3: Update content.py implementation**

Replace the entire contents of `src/amplifier_ipc/host/content.py` with:

```python
"""Content resolution — assemble system prompts from service context files.

Provides :func:`assemble_system_prompt` which gathers all ``context/``-prefixed
files from every registered service, recursively resolves ``@mention``
references via a :class:`~amplifier_ipc.host.mentions.MentionResolverChain`,
and deduplicates by SHA-256 hash before formatting as XML context-file blocks.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amplifier_ipc.host.mentions import MentionResolverChain

logger = logging.getLogger(__name__)


def _append_if_unique(
    content: str,
    key: str,
    seen_hashes: set[str],
    parts: list[str],
) -> None:
    """Append a ``<context_file>`` block only if its content hasn't been seen before.

    Args:
        content: The file content to deduplicate and format.
        key: The path identifier used in the ``<context_file path="…">`` attribute.
        seen_hashes: Mutable set of SHA-256 hex digests already added to *parts*.
        parts: Mutable list of formatted XML blocks being assembled.
    """
    h = hashlib.sha256(content.encode()).hexdigest()
    if h not in seen_hashes:
        seen_hashes.add(h)
        parts.append(f'<context_file path="{key}">\n{content}\n</context_file>')


async def assemble_system_prompt(
    registry: Any,
    services: dict[str, Any],
    *,
    resolver_chain: MentionResolverChain | None = None,
) -> str:
    """Assemble a deduplicated system prompt from service context files.

    Gathers every path whose name starts with ``context/`` from all services
    registered in *registry*, deduplicates content by SHA-256 hash, and wraps
    each unique piece of content in an XML ``<context_file>`` block.

    When *resolver_chain* is provided, each gathered file's content is scanned
    for ``@namespace:path`` mentions which are recursively resolved and appended.

    Args:
        registry: Service index mapping service keys to their content paths.
        services: Mapping of service key → service object.
        resolver_chain: Optional mention resolver chain for recursive
            ``@mention`` expansion within gathered content.

    Returns:
        A newline-joined string of ``<context_file path="…">…</context_file>``
        blocks, one per unique content item.
    """
    seen_hashes: set[str] = set()
    parts: list[str] = []

    content_services = registry.get_content_services()

    for service_key, paths in content_services.items():
        service = services.get(service_key)
        if service is None:
            continue

        for path in paths:
            if not path.startswith("context/"):
                continue

            try:
                result = await service.client.request("content.read", {"path": path})
                content: str = result["content"]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to read content %r from service %r: %s",
                    path,
                    service_key,
                    exc,
                )
                continue

            _append_if_unique(content, f"{service_key}:{path}", seen_hashes, parts)

            # Recursively resolve @mentions within this content
            if resolver_chain is not None:
                from amplifier_ipc.host.mentions import resolve_and_load  # noqa: PLC0415

                resolved = await resolve_and_load(
                    content, resolver_chain, seen_hashes=seen_hashes
                )
                for rc in resolved:
                    parts.append(
                        f'<context_file path="{rc.key}">'
                        f"\n{rc.content}\n</context_file>"
                    )

    return "\n".join(parts)
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_content.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/content.py tests/host/test_content.py && git commit -m "refactor(content): replace resolve_mention with resolver_chain parameter"
```

---

### Task 7: Update `host.py` — Create Chain + Pass to `assemble_system_prompt`

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Modify: `tests/host/test_host.py`

**Step 1: Write the failing test**

Add to `tests/host/test_host.py` (after existing imports and before the first test):

```python
async def test_host_has_mention_resolver_chain() -> None:
    """Host.__init__ creates a MentionResolverChain with NamespaceResolver."""
    from amplifier_ipc.host.mentions import MentionResolverChain

    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    assert isinstance(host.mention_resolver, MentionResolverChain)


async def test_host_mention_resolver_uses_mutable_refs() -> None:
    """NamespaceResolver holds references to mutable registry/services dicts.

    Verifies that the resolver can resolve mentions after services are
    populated (simulating what happens during run()).
    """
    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    # Before populating — should return None (no services registered)
    result = await host.mention_resolver.resolve("@foundation:agents/explorer.md")
    assert result is None

    # Populate registry and services (simulating _build_registry + _spawn_services)
    host._registry.register(
        "foundation",
        {
            "tools": [],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": ["agents/explorer.md"],
        },
    )
    host._services["foundation"] = FakeService(
        FakeClient({"agents/explorer.md": "explorer content"})
    )

    # After populating — resolver sees the updated data via mutable references
    result = await host.mention_resolver.resolve("@foundation:agents/explorer.md")
    assert result == "explorer content"
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_host_has_mention_resolver_chain -v`

Expected: FAIL — `AttributeError: 'Host' object has no attribute 'mention_resolver'`

**Step 3: Update host.py implementation**

Make two changes to `src/amplifier_ipc/host/host.py`:

**Change 1:** Add import at the top (after line 24, the `content` import):

```python
from amplifier_ipc.host.mentions import MentionResolverChain, NamespaceResolver
```

**Change 2:** Add the chain creation to `__init__`, after line 114 (`self._resume_session_id: str | None = None`):

```python
        # Mention resolution chain — NamespaceResolver is the default.
        # It holds *references* to the mutable _registry and _services dicts,
        # so it works once services are discovered during run().
        self.mention_resolver: MentionResolverChain = MentionResolverChain(
            [NamespaceResolver(self._registry, self._services)]
        )
```

**Change 3:** Update the `assemble_system_prompt` call in `run()`. Change line 405:

```python
            system_prompt = await assemble_system_prompt(self._registry, self._services)
```

to:

```python
            system_prompt = await assemble_system_prompt(
                self._registry, self._services,
                resolver_chain=self.mention_resolver,
            )
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_host_has_mention_resolver_chain tests/host/test_host.py::test_host_mention_resolver_uses_mutable_refs -v`

Expected: PASS

Also verify existing tests still pass:

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/host.py tests/host/test_host.py && git commit -m "feat(host): create MentionResolverChain in __init__, wire to assemble_system_prompt"
```

---

### Task 8: Working Directory Scanning in `host.py`

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Modify: `tests/host/test_host.py`

**Context:** After system prompt assembly, the host scans the working directory for `AGENTS.md`, `.amplifier/AGENTS.md`, and `.amplifier/*.md` files. These are read from the local filesystem, run through `resolve_and_load()`, and appended to the system prompt.

**Step 1: Write the failing test**

Add to `tests/host/test_host.py`:

```python
from pathlib import Path


async def test_host_load_working_dir_content(tmp_path: Path) -> None:
    """Scans working directory for AGENTS.md and .amplifier/*.md files."""
    # Create working directory content
    (tmp_path / "AGENTS.md").write_text("# Project Agents\nBe helpful.")
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    (amplifier_dir / "AGENTS.md").write_text("# Amplifier Agents\nBe precise.")
    (amplifier_dir / "custom.md").write_text("# Custom\nDo custom things.")

    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings(), working_dir=tmp_path)

    result = await host._load_working_dir_content()

    assert "Be helpful." in result
    assert "Be precise." in result
    assert "Do custom things." in result
    assert "<context_file" in result


async def test_host_load_working_dir_content_no_dir() -> None:
    """Returns empty string when working_dir is None."""
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    result = await host._load_working_dir_content()

    assert result == ""


async def test_host_load_working_dir_content_deduplicates(tmp_path: Path) -> None:
    """Same content in AGENTS.md and .amplifier/AGENTS.md is deduplicated."""
    (tmp_path / "AGENTS.md").write_text("identical content")
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    (amplifier_dir / "AGENTS.md").write_text("identical content")

    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings(), working_dir=tmp_path)

    result = await host._load_working_dir_content()

    assert result.count("identical content") == 1
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_host_load_working_dir_content -v`

Expected: FAIL — `TypeError: Host.__init__() got an unexpected keyword argument 'working_dir'`

**Step 3: Update host.py implementation**

**Change 1:** Add `working_dir` parameter to `Host.__init__` — add after `spawn_depth: int = 0,`:

```python
        working_dir: Path | None = None,
```

And in the body, after the `self.mention_resolver` assignment:

```python
        self._working_dir = working_dir
```

**Change 2:** Add the import of `resolve_and_load` at the top of the file (with the existing mentions import):

Update the existing import:
```python
from amplifier_ipc.host.mentions import MentionResolverChain, NamespaceResolver
```
to:
```python
from amplifier_ipc.host.mentions import (
    MentionResolverChain,
    NamespaceResolver,
    resolve_and_load,
)
```

**Change 3:** Add `_load_working_dir_content` method. Place it after the `run()` method and before `_build_spawn_handler`:

```python
    async def _load_working_dir_content(self) -> str:
        """Scan working directory for AGENTS.md and .amplifier/*.md files.

        Files are deduplicated by SHA-256 hash and recursively scanned for
        ``@mentions`` via :func:`resolve_and_load`.

        Returns:
            Newline-joined ``<context_file>`` XML blocks, or empty string
            if ``working_dir`` is ``None`` or no files are found.
        """
        if self._working_dir is None:
            return ""

        import hashlib  # noqa: PLC0415

        seen_hashes: set[str] = set()
        parts: list[str] = []

        candidates: list[Path] = []

        # Root AGENTS.md
        agents_md = self._working_dir / "AGENTS.md"
        if agents_md.is_file():
            candidates.append(agents_md)

        # .amplifier/ directory — all .md files
        amplifier_dir = self._working_dir / ".amplifier"
        if amplifier_dir.is_dir():
            for md_file in sorted(amplifier_dir.glob("*.md")):
                candidates.append(md_file)

        for file_path in candidates:
            try:
                content = file_path.read_text()
            except OSError:
                logger.warning("Failed to read working dir file %s", file_path)
                continue

            h = hashlib.sha256(content.encode()).hexdigest()
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            parts.append(
                f'<context_file path="{file_path}">'
                f"\n{content}\n</context_file>"
            )

            # Resolve @mentions in loaded content
            try:
                resolved = await resolve_and_load(
                    content, self.mention_resolver, seen_hashes=seen_hashes
                )
                for rc in resolved:
                    parts.append(
                        f'<context_file path="{rc.key}">'
                        f"\n{rc.content}\n</context_file>"
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to resolve mentions in %s", file_path
                )

        return "\n".join(parts)
```

**Change 4:** Call `_load_working_dir_content` in `run()`. After the `assemble_system_prompt` call (the one we updated in Task 7), add:

```python
            # 6b. Load working directory content
            working_dir_content = await self._load_working_dir_content()
            if working_dir_content:
                system_prompt = system_prompt + "\n" + working_dir_content
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_host_load_working_dir_content tests/host/test_host.py::test_host_load_working_dir_content_no_dir tests/host/test_host.py::test_host_load_working_dir_content_deduplicates -v`

Expected: PASS

Also run full test suite to check nothing broke:

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/host.py tests/host/test_host.py && git commit -m "feat(host): add working directory content scanning in run()"
```

---

### Task 9: `base` Field on `AgentDefinition`

**Files:**
- Modify: `src/amplifier_ipc/host/definitions.py`
- Modify: `tests/host/test_definitions.py` (if it exists, otherwise add test in `test_mentions.py`)

**Step 1: Verify test file exists**

Run: `ls tests/host/test_definitions.py` — if it exists, add tests there. Otherwise, add to a new test section in `tests/host/test_mentions.py`.

**Step 2: Write the failing test**

Add to the appropriate test file:

```python
from amplifier_ipc.host.definitions import AgentDefinition, parse_agent_definition


def test_agent_definition_base_field_default() -> None:
    """AgentDefinition.base defaults to None."""
    agent_def = AgentDefinition()
    assert agent_def.base is None


def test_parse_agent_definition_reads_base() -> None:
    """parse_agent_definition extracts the base field from YAML."""
    yaml_content = """
agent:
  ref: explorer
  base: foundation:agents/explorer.md
  description: An explorer agent
"""
    agent_def = parse_agent_definition(yaml_content)

    assert agent_def.ref == "explorer"
    assert agent_def.base == "foundation:agents/explorer.md"


def test_parse_agent_definition_base_absent() -> None:
    """parse_agent_definition sets base to None when not in YAML."""
    yaml_content = """
agent:
  ref: basic
  description: A basic agent
"""
    agent_def = parse_agent_definition(yaml_content)

    assert agent_def.base is None
```

**Step 3: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest <test_file>::test_agent_definition_base_field_default -v`

Expected: FAIL — `AgentDefinition.__init__() got an unexpected keyword argument 'base'` or similar

**Step 4: Update definitions.py**

**Change 1:** Add `base` field to `AgentDefinition` class. Add after line 52 (`orchestrator: str | None = None`):

```python
    base: str | None = None
```

**Change 2:** Update `parse_agent_definition` function. Add `base=data.get("base"),` to the `AgentDefinition(...)` constructor call, after the `ref=data.get("ref"),` line:

In the `return AgentDefinition(...)` call (around line 163), add:

```python
        base=data.get("base"),
```

after:

```python
        ref=data.get("ref"),
```

**Step 5: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest <test_file> -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/definitions.py tests/host/ && git commit -m "feat(definitions): add base field to AgentDefinition"
```

---

### Task 10: Agent `base:` Loading in Spawn Handler

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Modify: `tests/host/test_host.py`

**Context:** During agent spawn, when `agent_name != "self"`, the host looks up the agent definition, checks for a `base:` field, resolves it via the mention resolver chain, and prepends the resolved content to the spawn instruction.

**Step 1: Write the failing test**

Add to `tests/host/test_host.py`:

```python
from unittest.mock import patch, MagicMock
from pathlib import Path as StdPath


async def test_resolve_agent_base_returns_content() -> None:
    """_resolve_agent_base loads and resolves the agent's base file."""
    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    # Set up the mention resolver to return content for the base path
    async def fake_resolve(mention: str) -> str | None:
        if mention == "@foundation:agents/explorer.md":
            return "# Explorer\nExplore things.\n\nSee @foundation:context/tips.md"
        if mention == "@foundation:context/tips.md":
            return "Exploration tips"
        return None

    host.mention_resolver = MentionResolverChain([fake_resolve])

    # Mock the definition registry to return an agent with base
    fake_agent_path = MagicMock()
    fake_agent_path.read_text.return_value = """
agent:
  ref: explorer
  base: foundation:agents/explorer.md
"""
    fake_registry = MagicMock()
    fake_registry.resolve_agent.return_value = fake_agent_path

    with patch(
        "amplifier_ipc.host.host.Registry", return_value=fake_registry
    ):
        result = await host._resolve_agent_base("explorer")

    assert "Explore things." in result
    assert "Exploration tips" in result


async def test_resolve_agent_base_returns_empty_for_self() -> None:
    """_resolve_agent_base returns empty string for agent='self'."""
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    result = await host._resolve_agent_base("self")

    assert result == ""


async def test_resolve_agent_base_returns_empty_on_error() -> None:
    """_resolve_agent_base returns empty string when resolution fails."""
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    with patch(
        "amplifier_ipc.host.host.Registry",
        side_effect=FileNotFoundError("no registry"),
    ):
        result = await host._resolve_agent_base("nonexistent")

    assert result == ""
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_resolve_agent_base_returns_content -v`

Expected: FAIL — `AttributeError: 'Host' object has no attribute '_resolve_agent_base'`

**Step 3: Update host.py implementation**

**Change 1:** Add `_resolve_agent_base` method to the Host class. Place it after `_load_working_dir_content` and before `_build_spawn_handler`:

```python
    async def _resolve_agent_base(self, agent_name: str) -> str:
        """Resolve an agent's ``base:`` file and return its content.

        Looks up the agent definition via the definition registry, reads the
        ``base`` field (a ``namespace:path`` string), resolves it through
        :attr:`mention_resolver`, and recursively expands any nested
        ``@mentions``.

        Args:
            agent_name: The agent identifier.  ``"self"`` returns empty.

        Returns:
            The resolved base content (possibly with nested mentions expanded),
            or an empty string if the agent has no ``base:`` or resolution fails.
        """
        if agent_name == "self":
            return ""

        try:
            from amplifier_ipc.host.definition_registry import Registry  # noqa: PLC0415
            from amplifier_ipc.host.definitions import parse_agent_definition  # noqa: PLC0415

            reg = Registry()
            agent_path = reg.resolve_agent(agent_name)
            agent_def = parse_agent_definition(agent_path.read_text())

            if not agent_def.base:
                return ""

            # Resolve the base path via the mention chain
            content = await self.mention_resolver.resolve(f"@{agent_def.base}")
            if not content:
                return ""

            # Recursively resolve nested @mentions
            resolved = await resolve_and_load(content, self.mention_resolver)
            parts = [content]
            for rc in resolved:
                parts.append(rc.content)
            return "\n\n".join(parts)

        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to load agent base for %r", agent_name, exc_info=True
            )
            return ""
```

**Change 2:** Update `_build_spawn_handler` to call `_resolve_agent_base` and prepend to instruction. In the `_handle_spawn` closure (around line 471), after `agent_name = p.get("agent", "self")` and before creating `SpawnRequest`, add:

```python
            # Resolve agent base file content (if any)
            agent_base = await self._resolve_agent_base(agent_name)
            raw_instruction = p.get("instruction", "")
            if agent_base:
                raw_instruction = f"{agent_base}\n\n{raw_instruction}"
```

Then change the `SpawnRequest` construction to use `raw_instruction`:

```python
            spawn_request = SpawnRequest(
                agent=agent_name,
                instruction=raw_instruction,
                ...
            )
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_resolve_agent_base_returns_content tests/host/test_host.py::test_resolve_agent_base_returns_empty_for_self tests/host/test_host.py::test_resolve_agent_base_returns_empty_on_error -v`

Expected: PASS

Run full suite: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/host.py tests/host/test_host.py && git commit -m "feat(host): resolve agent base file during spawn"
```

---

### Task 11: Tool Input Pre-Processing

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Modify: `tests/host/test_host.py`

**Context:** Before routing `request.tool_execute` to a service, scan string arguments for `@namespace:path` mentions and resolve them through the chain. Single-level only (no recursion). If resolution fails, pass the unresolved `@` string intact.

**Step 1: Write the failing test**

Add to `tests/host/test_host.py`:

```python
async def test_preprocess_tool_mentions_resolves_arguments() -> None:
    """Resolves @mentions in tool execute argument strings."""
    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    async def fake_resolve(mention: str) -> str | None:
        if mention == "@foundation:context/common.md":
            return "resolved content"
        return None

    host.mention_resolver = MentionResolverChain([fake_resolve])

    params = {
        "name": "some_tool",
        "arguments": {
            "file_path": "@foundation:context/common.md",
            "plain_arg": "no mentions here",
            "number_arg": 42,
        },
    }

    result = await host._preprocess_tool_mentions(params)

    assert result["arguments"]["file_path"] == "resolved content"
    assert result["arguments"]["plain_arg"] == "no mentions here"
    assert result["arguments"]["number_arg"] == 42
    # Original params unchanged
    assert params["arguments"]["file_path"] == "@foundation:context/common.md"


async def test_preprocess_tool_mentions_leaves_unresolved() -> None:
    """Unresolved @mentions are left intact in argument strings."""
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    async def always_none(mention: str) -> str | None:
        return None

    host.mention_resolver = MentionResolverChain([always_none])

    params = {
        "name": "some_tool",
        "arguments": {"path": "@unknown:file.md"},
    }

    result = await host._preprocess_tool_mentions(params)

    assert result["arguments"]["path"] == "@unknown:file.md"


async def test_preprocess_tool_mentions_non_dict_passthrough() -> None:
    """Non-dict params are passed through unchanged."""
    config = SessionConfig(
        services=[],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    host = Host(config=config, settings=HostSettings())

    result = await host._preprocess_tool_mentions("not a dict")

    assert result == "not a dict"
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_preprocess_tool_mentions_resolves_arguments -v`

Expected: FAIL — `AttributeError: 'Host' object has no attribute '_preprocess_tool_mentions'`

**Step 3: Update host.py implementation**

**Change 1:** Add the import of `parse_mentions` to the existing mentions import at the top of host.py:

```python
from amplifier_ipc.host.mentions import (
    MentionResolverChain,
    NamespaceResolver,
    parse_mentions,
    resolve_and_load,
)
```

**Change 2:** Add `_preprocess_tool_mentions` method to Host. Place it near `_handle_orchestrator_request`:

```python
    async def _preprocess_tool_mentions(self, params: Any) -> Any:
        """Resolve ``@namespace:path`` mentions in tool argument strings.

        Scans each string-valued argument for ``@mentions``, resolves them
        through :attr:`mention_resolver`, and replaces matches with the
        resolved content.  Single-level only (no recursion into resolved
        content).

        Non-dict *params* or non-dict ``arguments`` are returned unchanged.
        Unresolved mentions are left intact with a warning logged.

        Returns:
            A shallow copy of *params* with resolved argument values.
        """
        if not isinstance(params, dict):
            return params
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            return params

        modified_args = dict(arguments)
        changed = False

        for key, value in arguments.items():
            if not isinstance(value, str):
                continue
            mentions = parse_mentions(value)
            if not mentions:
                continue

            new_value = value
            for mention in mentions:
                try:
                    resolved = await self.mention_resolver.resolve(mention)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to resolve mention %r in tool argument %r",
                        mention,
                        key,
                    )
                    continue

                if resolved is not None:
                    new_value = new_value.replace(mention, resolved)
                    changed = True
                else:
                    logger.debug(
                        "Unresolved mention %r in tool argument %r",
                        mention,
                        key,
                    )

            modified_args[key] = new_value

        if not changed:
            return params

        result = dict(params)
        result["arguments"] = modified_args
        return result
```

**Change 3:** Wire into `_handle_orchestrator_request`. Change the method body to pre-process tool execute requests:

```python
    async def _handle_orchestrator_request(self, method: str, params: Any) -> Any:
        """Delegate an orchestrator request to the :class:`Router`.

        For ``request.tool_execute``, argument strings are pre-processed to
        resolve ``@namespace:path`` mentions before routing.
        """
        if self._router is None:
            raise RuntimeError("Router has not been initialised")
        if method == "request.tool_execute":
            params = await self._preprocess_tool_mentions(params)
        return await self._router.route_request(method, params)
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py::test_preprocess_tool_mentions_resolves_arguments tests/host/test_host.py::test_preprocess_tool_mentions_leaves_unresolved tests/host/test_host.py::test_preprocess_tool_mentions_non_dict_passthrough -v`

Expected: PASS

Run full suite: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/ -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/host.py tests/host/test_host.py && git commit -m "feat(host): pre-process @mentions in tool execute arguments"
```

---

### Task 12: Update `__init__.py` Exports

**Files:**
- Modify: `src/amplifier_ipc/host/__init__.py`

**Context:** The `resolve_mention` function was removed from `content.py` and needs to be removed from exports. The new mentions module needs to be exported.

**Step 1: Run type checks to catch stale imports**

Run: `cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.host import resolve_mention"` — this should fail.

Run: `cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.host.mentions import MentionResolverChain, NamespaceResolver, WorkingDirResolver, parse_mentions, resolve_and_load, ResolvedContent"` — this should succeed.

**Step 2: Update __init__.py**

In `src/amplifier_ipc/host/__init__.py`:

**Change 1:** Update the content import (line 11):

```python
from amplifier_ipc.host.content import assemble_system_prompt, resolve_mention
```

to:

```python
from amplifier_ipc.host.content import assemble_system_prompt
```

**Change 2:** Add mentions module imports (after the content import):

```python
from amplifier_ipc.host.mentions import (
    MentionResolverChain,
    NamespaceResolver,
    ResolvedContent,
    WorkingDirResolver,
    parse_mentions,
    resolve_and_load,
)
```

**Change 3:** Update `__all__` list. Remove `"resolve_mention"` (around line 99) and add the mentions exports. Replace the `# Content` section:

```python
    # Content
    "resolve_mention",
    "assemble_system_prompt",
```

with:

```python
    # Content
    "assemble_system_prompt",
    # Mentions
    "MentionResolverChain",
    "NamespaceResolver",
    "WorkingDirResolver",
    "ResolvedContent",
    "parse_mentions",
    "resolve_and_load",
```

**Step 3: Verify imports work**

Run: `cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.host import MentionResolverChain, NamespaceResolver, WorkingDirResolver, parse_mentions, resolve_and_load, ResolvedContent; print('OK')""`

Expected: `OK`

Run: `cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.host import resolve_mention"` — should FAIL with `ImportError`

**Step 4: Run full test suite**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/ -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/__init__.py && git commit -m "refactor(host): update __init__.py exports for mentions module"
```

---

## Final Verification

After all 12 tasks are complete, run the full test suite:

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/ -v
```

All tests should pass. If there are failures in other test modules that import `resolve_mention`, search for them:

```bash
cd /data/labs/amplifier-ipc && grep -r "resolve_mention" tests/
```

Fix any remaining references to the removed function.

---

## Summary

| Task | Component | Files | Tests |
|------|-----------|-------|-------|
| 1 | `parse_mentions()` | mentions.py | 10 new |
| 2 | `MentionResolver` + `NamespaceResolver` | mentions.py | 5 new |
| 3 | `WorkingDirResolver` | mentions.py | 5 new |
| 4 | `MentionResolverChain` | mentions.py | 6 new |
| 5 | `resolve_and_load()` | mentions.py | 7 new |
| 6 | Update `content.py` | content.py, test_content.py | 3 updated |
| 7 | Host chain creation | host.py, test_host.py | 2 new |
| 8 | Working dir scanning | host.py, test_host.py | 3 new |
| 9 | `AgentDefinition.base` | definitions.py | 3 new |
| 10 | Agent base loading | host.py, test_host.py | 3 new |
| 11 | Tool input pre-processing | host.py, test_host.py | 3 new |
| 12 | `__init__.py` exports | `__init__.py` | verification only |

**Total: 12 tasks, ~50 new tests, 4 modified files, 2 new files**
