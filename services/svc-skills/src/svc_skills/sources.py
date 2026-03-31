"""Skill source resolution for git URLs and remote sources.

Handles fetching skills from git repositories and caching them locally.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default cache directory for remote skills
DEFAULT_SKILLS_CACHE_DIR = Path("~/.amplifier/cache/skills").expanduser()


def is_remote_source(source: str) -> bool:
    """Check if a source string is a remote URL (git+https://, etc.)."""
    return (
        source.startswith("git+")
        or source.startswith("https://")
        or source.startswith("http://")
    )


async def resolve_skill_source(
    source: str, cache_dir: Path | None = None
) -> Path | None:
    """Resolve a skill source to a local directory path."""
    cache_dir = cache_dir or DEFAULT_SKILLS_CACHE_DIR

    if not is_remote_source(source):
        path = Path(source).expanduser().resolve()
        if path.exists():
            return path
        logger.debug(f"Local skill source does not exist: {path}")
        return None

    try:
        return await _resolve_remote_source(source, cache_dir)
    except Exception as e:
        logger.warning(f"Failed to resolve remote skill source '{source}': {e}")
        return None


async def _resolve_remote_source(source: str, cache_dir: Path) -> Path | None:
    """Resolve a remote source URL by cloning the git repository."""
    import hashlib
    import subprocess

    url = source
    if url.startswith("git+"):
        url = url[4:]

    subdirectory = None
    if "#subdirectory=" in url:
        url, fragment = url.split("#", 1)
        if fragment.startswith("subdirectory="):
            subdirectory = fragment[13:]

    ref = "main"
    if "@" in url:
        url, ref = url.rsplit("@", 1)

    cache_key = hashlib.sha256(f"{url}@{ref}".encode()).hexdigest()[:16]
    repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    cache_path = cache_dir / f"{repo_name}-{cache_key}"

    if cache_path.exists():
        logger.debug(f"Using cached skill source: {cache_path}")
        result_path = cache_path / subdirectory if subdirectory else cache_path
        if result_path.exists():
            return result_path

    cache_dir.mkdir(parents=True, exist_ok=True)

    try:
        if cache_path.exists():
            import shutil

            shutil.rmtree(cache_path)

        cmd = ["git", "clone", "--depth", "1", "--branch", ref, url, str(cache_path)]
        logger.info(f"Cloning skill source: {url}@{ref}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            logger.error(f"Git clone failed: {result.stderr}")
            return None

        result_path = cache_path / subdirectory if subdirectory else cache_path
        if result_path.exists():
            logger.info(f"Resolved remote skill source: {source} -> {result_path}")
            return result_path
        else:
            logger.warning(f"Subdirectory not found in cloned repo: {subdirectory}")
            return None

    except subprocess.TimeoutExpired:
        logger.error(f"Git clone timed out for: {url}")
        return None
    except Exception as e:
        logger.error(f"Failed to clone skill source '{source}': {e}")
        return None


async def resolve_skill_sources(
    sources: list[str], cache_dir: Path | None = None
) -> list[Path]:
    """Resolve multiple skill sources to local directory paths."""
    cache_dir = cache_dir or DEFAULT_SKILLS_CACHE_DIR

    local_sources: list[tuple[int, str]] = []
    remote_sources: list[tuple[int, str]] = []

    for i, source in enumerate(sources):
        if is_remote_source(source):
            remote_sources.append((i, source))
        else:
            local_sources.append((i, source))

    results: dict[int, Path | None] = {}
    for i, source in local_sources:
        path = Path(source).expanduser().resolve()
        if path.exists():
            results[i] = path
        else:
            logger.debug(f"Local skill source does not exist: {path}")
            results[i] = None

    if remote_sources:

        async def resolve_with_index(i: int, source: str) -> tuple[int, Path | None]:
            path = await resolve_skill_source(source, cache_dir)
            return (i, path)

        tasks = [resolve_with_index(i, source) for i, source in remote_sources]
        remote_results = await asyncio.gather(*tasks)

        for i, path in remote_results:
            results[i] = path

    resolved_paths: list[Path] = []
    for i in sorted(results.keys()):
        path = results[i]
        if path is not None:
            resolved_paths.append(path)

    logger.info(
        f"Resolved {len(resolved_paths)} skill sources from {len(sources)} configured"
    )
    return resolved_paths
