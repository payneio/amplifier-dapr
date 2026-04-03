"""Tests for services/svc-content-foundation scaffold — validates directory structure and Dockerfile.

TDD: These tests were written BEFORE the files were created.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent
SVC_DIR = REPO_ROOT / "services" / "svc-content-foundation"
DOCKERFILE_PATH = SVC_DIR / "Dockerfile"
GITKEEP_PATH = SVC_DIR / "content" / ".gitkeep"


def _dockerfile_content() -> str:
    """Return the Dockerfile content (fails with clear message if missing)."""
    assert DOCKERFILE_PATH.exists(), (
        f"Dockerfile not found at {DOCKERFILE_PATH}. "
        "Create services/svc-content-foundation/Dockerfile per spec."
    )
    return DOCKERFILE_PATH.read_text()


# ── File existence ─────────────────────────────────────────────────────────────


def test_dockerfile_exists() -> None:
    """Dockerfile exists at services/svc-content-foundation/Dockerfile."""
    assert DOCKERFILE_PATH.exists(), f"Expected {DOCKERFILE_PATH} to exist"


def test_gitkeep_exists() -> None:
    """Placeholder file exists at services/svc-content-foundation/content/.gitkeep."""
    assert GITKEEP_PATH.exists(), f"Expected {GITKEEP_PATH} to exist"


def test_exactly_two_files_in_service_dir() -> None:
    """Directory contains exactly Dockerfile and content/.gitkeep (no extras)."""
    result = subprocess.run(
        ["find", str(SVC_DIR), "-type", "f"],
        capture_output=True,
        text=True,
        check=True,
    )
    found_files = sorted(result.stdout.strip().splitlines())
    expected_files = sorted([str(DOCKERFILE_PATH), str(GITKEEP_PATH)])
    assert found_files == expected_files, (
        f"Expected exactly {expected_files}, got {found_files}"
    )


# ── Dockerfile Stage 1: amplifier-service-base ────────────────────────────────


def test_stage1_from_python_312_slim() -> None:
    """Stage 1 must use python:3.12-slim as the base image."""
    content = _dockerfile_content()
    assert re.search(r"^FROM\s+python:3\.12-slim\s+AS\s+amplifier-service-base", content, re.MULTILINE), (
        "Stage 1 must be: FROM python:3.12-slim AS amplifier-service-base"
    )


def test_stage1_workdir_is_app() -> None:
    """Stage 1 must set WORKDIR /app."""
    content = _dockerfile_content()
    assert re.search(r"^WORKDIR\s+/app\b", content, re.MULTILINE), (
        "Dockerfile must set 'WORKDIR /app'"
    )


def test_stage1_installs_uv() -> None:
    """Stage 1 must install uv with --no-cache-dir."""
    content = _dockerfile_content()
    assert "pip install --no-cache-dir uv" in content, (
        "Dockerfile must install uv with: pip install --no-cache-dir uv"
    )


def test_stage1_copies_sdk_to_build() -> None:
    """Stage 1 must copy amplifier-service-sdk/ into /build/amplifier-service-sdk/."""
    content = _dockerfile_content()
    assert re.search(
        r"COPY\s+amplifier-service-sdk/\s+/build/amplifier-service-sdk/",
        content,
    ), "Dockerfile must COPY amplifier-service-sdk/ /build/amplifier-service-sdk/"


def test_stage1_installs_sdk_system_wide() -> None:
    """Stage 1 must install the SDK system-wide via uv pip install --system."""
    content = _dockerfile_content()
    assert "uv pip install --system ." in content, (
        "Dockerfile must run 'uv pip install --system .' inside the SDK directory"
    )


def test_stage1_removes_build_dir() -> None:
    """Stage 1 must remove the /build directory after SDK installation."""
    content = _dockerfile_content()
    assert "rm -rf /build" in content, "Dockerfile must clean up with 'rm -rf /build'"


def test_stage1_healthcheck_configured() -> None:
    """Stage 1 HEALTHCHECK must use interval=10s, timeout=3s, retries=3."""
    content = _dockerfile_content()
    hc = re.search(r"HEALTHCHECK\s+(.+)", content)
    assert hc, "Dockerfile must contain a HEALTHCHECK instruction"
    hc_line = hc.group(1)
    assert "--interval=10s" in hc_line, "HEALTHCHECK must set --interval=10s"
    assert "--timeout=3s" in hc_line, "HEALTHCHECK must set --timeout=3s"
    assert "--retries=3" in hc_line, "HEALTHCHECK must set --retries=3"


def test_stage1_healthcheck_probes_localhost_8000() -> None:
    """Stage 1 HEALTHCHECK CMD must probe http://localhost:8000/healthz via urllib."""
    content = _dockerfile_content()
    assert "urllib" in content, "HEALTHCHECK must use Python's urllib"
    assert "healthz" in content, "HEALTHCHECK must probe the /healthz endpoint"
    assert "localhost:8000" in content, "HEALTHCHECK must probe http://localhost:8000/healthz"


def test_stage1_exposes_port_8000() -> None:
    """Stage 1 must EXPOSE port 8000."""
    content = _dockerfile_content()
    assert re.search(r"^EXPOSE\s+8000\b", content, re.MULTILINE), (
        "Dockerfile must EXPOSE 8000"
    )


# ── Dockerfile Stage 2: svc-content-foundation ────────────────────────────────


def test_stage2_from_amplifier_service_base() -> None:
    """Stage 2 must be FROM amplifier-service-base (no alias)."""
    content = _dockerfile_content()
    assert re.search(r"^FROM\s+amplifier-service-base\s*$", content, re.MULTILINE), (
        "Stage 2 must be: FROM amplifier-service-base"
    )


def test_stage2_copies_describe_yaml() -> None:
    """Stage 2 must copy services/svc-content-foundation/describe.yaml to /app/describe.yaml."""
    content = _dockerfile_content()
    assert re.search(
        r"COPY\s+services/svc-content-foundation/describe\.yaml\s+/app/describe\.yaml",
        content,
    ), "Stage 2 must COPY services/svc-content-foundation/describe.yaml /app/describe.yaml"


def test_stage2_copies_content_dir() -> None:
    """Stage 2 must copy services/svc-content-foundation/content/ to /app/content/."""
    content = _dockerfile_content()
    assert re.search(
        r"COPY\s+services/svc-content-foundation/content/\s+/app/content/",
        content,
    ), "Stage 2 must COPY services/svc-content-foundation/content/ /app/content/"


def test_stage2_cmd_runs_amplifier_serve() -> None:
    """Stage 2 CMD must run amplifier-serve with --config /app/describe.yaml."""
    content = _dockerfile_content()
    assert re.search(
        r'CMD\s+\["amplifier-serve",\s*"--config",\s*"/app/describe\.yaml"\]',
        content,
    ), 'Stage 2 must have CMD ["amplifier-serve", "--config", "/app/describe.yaml"]'
