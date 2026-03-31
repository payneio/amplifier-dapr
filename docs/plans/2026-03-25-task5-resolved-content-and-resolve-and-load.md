# Task 5: ResolvedContent + resolve_and_load() Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

> **HUMAN REVIEWER WARNING:** The automated spec review loop exhausted after
> 3 iterations without formal approval. The final (3rd) iteration verdict was
> "APPROVED" with all 33 tests passing and all 10 spec requirements verified,
> but the loop-exit mechanism flagged the task as unresolved. A human reviewer
> should confirm the implementation matches intent before proceeding to
> downstream tasks (Task 6+) that depend on `resolve_and_load`.

**Goal:** Add a `ResolvedContent` dataclass and a `resolve_and_load()` function
that recursively resolves `@mentions` in text using a resolver chain, with
SHA-256 content deduplication and a configurable depth limit.

**Architecture:** `resolve_and_load` is a synchronous recursive function that
uses `parse_mentions` (already implemented in Tasks 1-4) to find mentions,
resolves each via a chain object's `.resolve()` method, deduplicates by SHA-256
hash, and recurses into resolved content. A private `_ResolvableChain` Protocol
provides the type contract for the `chain` parameter.

**Tech Stack:** Python 3.12+, pytest with `asyncio_mode = "auto"`, dataclasses,
hashlib, uv

**Dependencies:** Tasks 1-4 must be complete. This task builds on
`parse_mentions`, `MentionResolverChain`, and the existing test infrastructure
in `tests/host/test_mentions.py`.

---

### Task 5a: Add test helpers for resolve_and_load

**Files:**
- Modify: `tests/host/test_mentions.py`

**Step 1: Add the FakeChain and ExplodingChain test helpers**

Append the following after the existing `MentionResolverChain` tests (after line
338 in the current file, after `test_chain_append`):

```python
# ---------------------------------------------------------------------------
# Helpers for resolve_and_load tests
# ---------------------------------------------------------------------------


class FakeChain:
    """Fake chain that maps mentions to fixed content strings."""

    def __init__(self, mapping: dict[str, str | None]) -> None:
        self._mapping = mapping

    def resolve(self, mention: str) -> str | None:
        return self._mapping.get(mention)


class ExplodingChain:
    """Chain whose resolve() always raises RuntimeError."""

    def resolve(self, mention: str) -> str | None:
        raise RuntimeError("Resolver exploded!")
```

These helpers have a sync `.resolve()` method matching the `_ResolvableChain`
Protocol that `resolve_and_load` will use. `FakeChain` returns content from
a dict (or `None` for missing keys). `ExplodingChain` always raises.

**Step 2: Run tests to verify nothing is broken**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 26 existing tests PASS (helpers add no tests themselves).

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add tests/host/test_mentions.py && git commit -m "test(mentions): add FakeChain and ExplodingChain helpers for resolve_and_load tests"
```

---

### Task 5b: Write the 7 failing tests for resolve_and_load

**Files:**
- Modify: `tests/host/test_mentions.py`

**Step 1: Add the import for ResolvedContent and resolve_and_load**

Update the import block at the top of `tests/host/test_mentions.py`. Change:

```python
from amplifier_ipc.host.mentions import (
    MentionResolverChain,
    NamespaceResolver,
    WorkingDirResolver,
    parse_mentions,
)
```

to:

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

Also add `import hashlib` to the top-level imports if not already present.

**Step 2: Add the 7 test functions**

Append after the `ExplodingChain` class:

```python
# ---------------------------------------------------------------------------
# Tests: resolve_and_load
# ---------------------------------------------------------------------------


def test_resolve_and_load_resolves_mentions() -> None:
    """Basic: resolves mentions in text and returns a ResolvedContent list."""
    chain = FakeChain({"@ns:a.md": "Content of A"})
    results = resolve_and_load("Load @ns:a.md here", chain)  # type: ignore[arg-type]
    assert len(results) == 1
    assert isinstance(results[0], ResolvedContent)
    assert results[0].key == "ns:a.md"
    assert results[0].content == "Content of A"


def test_resolve_and_load_recursive() -> None:
    """Resolved content that itself contains mentions is recursively loaded."""
    chain = FakeChain(
        {
            "@ns:a.md": "Load @ns:b.md here",
            "@ns:b.md": "Content of B",
        }
    )
    results = resolve_and_load("Load @ns:a.md here", chain)
    keys = [r.key for r in results]
    assert "ns:a.md" in keys
    assert "ns:b.md" in keys


def test_resolve_and_load_deduplicates_by_hash() -> None:
    """Two mentions resolving to identical content (same hash) produce only one result."""
    chain = FakeChain(
        {
            "@ns:a.md": "Same content",
            "@ns:b.md": "Same content",
        }
    )
    results = resolve_and_load("Load @ns:a.md and @ns:b.md here", chain)
    assert len(results) == 1


def test_resolve_and_load_depth_limit() -> None:
    """max_depth <= 0 returns an empty list immediately."""
    chain = FakeChain({"@ns:a.md": "Content of A"})
    results = resolve_and_load("Load @ns:a.md here", chain, max_depth=0)
    assert results == []


def test_resolve_and_load_shared_seen_hashes() -> None:
    """Passing an already-populated seen_hashes set prevents re-resolving content."""
    content = "Content of A"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    seen: set[str] = {content_hash}
    chain = FakeChain({"@ns:a.md": content})
    results = resolve_and_load("Load @ns:a.md here", chain, seen_hashes=seen)
    assert results == []


def test_resolve_and_load_skips_unresolved() -> None:
    """Mentions for which the chain returns None are silently skipped."""
    chain = FakeChain(
        {
            "@ns:a.md": None,
            "@ns:b.md": "Content of B",
        }
    )
    results = resolve_and_load("Load @ns:a.md and @ns:b.md here", chain)
    assert len(results) == 1
    assert results[0].key == "ns:b.md"


def test_resolve_and_load_handles_resolver_exception() -> None:
    """Exceptions raised by chain.resolve() are caught; the mention is skipped."""
    results = resolve_and_load("Load @ns:a.md here", ExplodingChain())
    assert results == []
```

**Important notes for the implementer:**
- These tests are **synchronous** (`def`, not `async def`). `resolve_and_load`
  is a sync function.
- `FakeChain` is passed where a `_ResolvableChain` Protocol is expected.
  The `# type: ignore[arg-type]` on the first test acknowledges this; pyright
  may flag `FakeChain` as not matching `_ResolvableChain` due to Protocol
  structural typing details. The `type: ignore` comment is acceptable.
- `ExplodingChain()` in the last test is passed directly (no type ignore needed
  since it also has `.resolve()`).

**Step 3: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py::test_resolve_and_load_resolves_mentions -v`

Expected: FAIL — `ImportError: cannot import name 'ResolvedContent' from 'amplifier_ipc.host.mentions'`

**Step 4: Commit the failing tests**

```bash
cd /data/labs/amplifier-ipc && git add tests/host/test_mentions.py && git commit -m "test(mentions): add 7 failing tests for resolve_and_load"
```

---

### Task 5c: Implement _ResolvableChain Protocol and ResolvedContent dataclass

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py`

**Step 1: Add the Protocol and dataclass**

Append the following after the `parse_mentions` function (after line 216 in the
current file):

```python
# ---------------------------------------------------------------------------
# ResolvedContent and resolve_and_load
# ---------------------------------------------------------------------------


@runtime_checkable
class _ResolvableChain(Protocol):
    """Structural protocol for sync resolver chains accepted by :func:`resolve_and_load`."""

    def resolve(self, mention: str) -> str | None:  # pragma: no cover
        ...


@dataclass
class ResolvedContent:
    """A resolved mention with its key (without ``@`` prefix) and content."""

    key: str
    """The mention string without the leading ``@``."""

    content: str
    """The resolved content of the mention."""
```

**Important notes for the implementer:**
- `runtime_checkable` is already imported at line 22 (`from typing import ...,
  runtime_checkable`). If you're implementing from scratch, ensure it's in the
  imports.
- `dataclass` is already imported at line 20 (`from dataclasses import
  dataclass`).
- `_ResolvableChain` is a **private** Protocol (prefixed with `_`). It is NOT
  exported. It exists solely to type-annotate the `chain` parameter.
- `ResolvedContent` uses `@dataclass`, not `pydantic.BaseModel`. It has exactly
  two fields: `key: str` and `content: str`.

**Step 2: Verify imports resolve**

Run: `cd /data/labs/amplifier-ipc && uv run python -c "from amplifier_ipc.host.mentions import ResolvedContent; print(ResolvedContent)"`

Expected: `<class 'amplifier_ipc.host.mentions.ResolvedContent'>`

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py && git commit -m "feat(mentions): add _ResolvableChain protocol and ResolvedContent dataclass"
```

---

### Task 5d: Implement resolve_and_load()

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py`

**Step 1: Add the function**

Append immediately after the `ResolvedContent` dataclass:

```python
def resolve_and_load(
    text: str,
    chain: _ResolvableChain,
    *,
    seen_hashes: set[str] | None = None,
    max_depth: int = 3,
) -> list[ResolvedContent]:
    """Recursively resolve and load ``@mention`` references found in *text*.

    For each unique mention in *text*:

    1. Resolves via *chain*.
    2. Skips ``None`` results and exceptions from the resolver.
    3. Deduplicates by SHA-256 hash of the content so identical files loaded
       via different mentions are not returned twice.
    4. Recurses into the resolved content (up to *max_depth* levels deep),
       sharing the same *seen_hashes* set so no content is emitted twice across
       the entire traversal.

    Args:
        text: The source text to scan for mentions.
        chain: Resolver chain used to resolve each mention.
        seen_hashes: Set of already-seen SHA-256 hashes (shared across
            recursive calls). If ``None`` a fresh set is created.
        max_depth: Maximum recursion depth. ``0`` returns ``[]`` immediately.

    Returns:
        Ordered list of :class:`ResolvedContent` items (parent before children).
    """
    if max_depth <= 0:
        return []

    if seen_hashes is None:
        seen_hashes = set()

    results: list[ResolvedContent] = []

    for mention in parse_mentions(text):
        try:
            content = chain.resolve(mention)
        except Exception:
            logger.warning(
                "resolve_and_load: resolver raised an exception for %r", mention
            )
            continue

        if content is None:
            continue

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if content_hash in seen_hashes:
            continue

        seen_hashes.add(content_hash)

        resolved = ResolvedContent(key=mention.lstrip("@"), content=content)
        results.append(resolved)

        nested = resolve_and_load(
            content,
            chain,
            seen_hashes=seen_hashes,
            max_depth=max_depth - 1,
        )
        results.extend(nested)

    return results
```

**Important notes for the implementer:**
- This function is **synchronous** (`def`, not `async def`). The chain's
  `.resolve()` method is also sync. This is intentional — see commit 6741ef5
  which documents the sync-only constraint on `MentionResolverChain.resolve()`.
- `hashlib` is already imported at line 17.
- `logger` is already defined at line 26.
- `parse_mentions` is defined earlier in the same module (line 199).
- The `seen_hashes` set is **shared** across recursive calls (mutable default
  pattern with `None` sentinel). This is what enables cross-call deduplication.
- The `key` field strips the `@` prefix: `mention.lstrip("@")`.

**Step 2: Run all 33 tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All 33 tests PASS (26 from Tasks 1-4 + 7 new)

**Step 3: Run the specific 7 new tests to confirm**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -k "resolve_and_load" -v`

Expected output:
```
test_resolve_and_load_resolves_mentions PASSED
test_resolve_and_load_recursive PASSED
test_resolve_and_load_deduplicates_by_hash PASSED
test_resolve_and_load_depth_limit PASSED
test_resolve_and_load_shared_seen_hashes PASSED
test_resolve_and_load_skips_unresolved PASSED
test_resolve_and_load_handles_resolver_exception PASSED
```

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/host/mentions.py && git commit -m "feat(mentions): implement resolve_and_load with recursive SHA-256 dedup"
```